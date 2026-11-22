"""LLM adapter: JSON-only chat, one repair attempt, and a token ledger.

The adapter never logs an API key or raw authorization header. A malformed JSON
answer is retried once with the exact parse error; a second failure raises a
typed contract error so the agent degrades instead of guessing.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.errors import ContractError, PermanentProviderError
from cfb_upset.ids import Clock, SystemClock
from cfb_upset.observability.budget import Budget

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LedgerEntry:
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: datetime
    run_id: str | None = None
    agent: str | None = None


class TokenLedger:
    """Append-only per-process token usage ledger."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def add(
        self,
        *,
        provider: str,
        model: str,
        usage: dict[str, Any],
        created_at: datetime,
        run_id: str | None = None,
        agent: str | None = None,
    ) -> LedgerEntry:
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        entry = LedgerEntry(
            provider=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            created_at=created_at,
            run_id=run_id,
            agent=agent,
        )
        with self._lock:
            self.entries.append(entry)
        return entry

    @property
    def total_prompt_tokens(self) -> int:
        return sum(entry.prompt_tokens for entry in self.entries)

    @property
    def total_completion_tokens(self) -> int:
        return sum(entry.completion_tokens for entry in self.entries)

    @property
    def total_tokens(self) -> int:
        return sum(entry.total_tokens for entry in self.entries)

    def summary(self) -> dict[str, int]:
        return {
            "calls": len(self.entries),
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }


class LlmClient:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        clock: Clock | None = None,
        ledger: TokenLedger | None = None,
        timeout_s: float = 60.0,
        budget: Budget | None = None,
        agent: str | None = None,
        run_id: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.vt_arc_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.arc_key
        self.model = model or settings.vt_arc_model
        self.clock = clock or SystemClock()
        self.ledger = ledger or TokenLedger()
        self.timeout_s = timeout_s
        self.budget = budget
        self.agent = agent
        self.run_id = run_id
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider="arc")
            self._owns_transport = True
        return self._transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def chat_text(
        self,
        *,
        system: str | None,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        messages = _messages(system, user)
        return await self._chat(messages, max_tokens=max_tokens, temperature=temperature)

    async def chat_json(
        self,
        *,
        system: str | None,
        user: str,
        response_model: type[T],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        repair: bool = True,
    ) -> T:
        messages = _messages(system, user)
        content = await self._chat(messages, max_tokens=max_tokens, temperature=temperature)
        try:
            return _parse_model(content, response_model)
        except ContractError as first_error:
            if not repair:
                raise
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was not valid JSON for the requested schema. "
                        f"Error: {first_error}. Return only the JSON object."
                    ),
                }
            )
            repaired = await self._chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return _parse_model(repaired, response_model)

    async def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if self.budget is not None:
            self.budget.check("llm")
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response = await self._transport_or_default().post(
            f"{self.base_url}/chat/completions",
            payload=payload,
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise PermanentProviderError(
                f"ARC chat returned HTTP {response.status_code}",
                status_code=response.status_code,
                provider="arc",
            )
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            raise PermanentProviderError(f"ARC chat error: {body['error']}", provider="arc")
        usage = body.get("usage") or {}
        entry = self.ledger.add(
            provider="arc",
            model=self.model,
            usage=usage,
            created_at=self.clock.now(),
            run_id=self.run_id,
            agent=self.agent,
        )
        if self.budget is not None and entry.total_tokens:
            self.budget.consume_tokens(entry.total_tokens, phase="llm")
        return _content_from(body)

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "ledger": self.ledger.summary(),
        }


def _messages(system: str | None, user: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


def _content_from(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise ContractError("LLM response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        content = message.get("reasoning_content") or message.get("reasoning")
    if not content:
        raise ContractError("LLM response has no message content")
    return str(content)


def _parse_model(content: str, response_model: type[T]) -> T:
    text = _json_text(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"LLM answer is not valid JSON: {exc}") from exc
    try:
        return response_model.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError -> typed contract error
        raise ContractError(f"LLM JSON does not match {response_model.__name__}: {exc}") from exc


def _json_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") or text.startswith("["):
        return text
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


__all__ = ["LedgerEntry", "LlmClient", "TokenLedger"]
