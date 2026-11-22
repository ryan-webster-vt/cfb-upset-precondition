"""LLM adapter: JSON gate, one repair, token ledger, and budget enforcement."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cfb_upset.adapters.llm import LlmClient, TokenLedger
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.contracts import StrictModel
from cfb_upset.errors import BudgetExhausted, ContractError, PermanentProviderError
from cfb_upset.ids import FrozenClock
from cfb_upset.observability.budget import Budget

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class OkModel(StrictModel):
    ok: bool


def load_chat_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "arc" / "chat_json.json").read_text())


def _response(content: str, *, total_tokens: int = 5) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": total_tokens - 3,
            "total_tokens": total_tokens,
        },
    }


def _mentions(payload: Any, needle: str) -> bool:
    if not isinstance(payload, dict):
        return False
    text = json.dumps(payload.get("messages") or [])
    return needle in text


async def test_chat_json_matches_the_captured_fixture() -> None:
    fixture = load_chat_fixture()
    transport = FixtureTransport().add("/chat/completions", fixture["response"])
    ledger = TokenLedger()
    client = LlmClient(
        transport,
        base_url="https://arc.example",
        api_key="test-key",
        model="GLM-5.3",
        clock=FrozenClock(NOW),
        ledger=ledger,
        agent="Upset-Scorer",
        run_id="run-1",
    )

    result = await client.chat_json(
        system=None,
        user=fixture["request"]["messages"][0]["content"],
        response_model=OkModel,
        max_tokens=fixture["request"]["max_tokens"],
    )
    assert result.ok is True
    assert transport.calls[0].payload["model"] == fixture["request"]["model"]
    assert ledger.total_tokens == 94


async def test_chat_json_parses_a_strict_model_and_records_usage() -> None:
    transport = FixtureTransport().add("/chat/completions", _response('{"ok": true}'))
    ledger = TokenLedger()
    client = LlmClient(
        transport,
        base_url="https://arc.example",
        api_key="test-key",
        model="GLM-5.3",
        clock=FrozenClock(NOW),
        ledger=ledger,
        agent="Upset-Scorer",
        run_id="run-1",
    )
    result = await client.chat_json(system="system", user="user", response_model=OkModel)
    assert result.ok is True
    assert ledger.summary() == {
        "calls": 1,
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    entry = ledger.entries[0]
    assert entry.created_at == NOW
    assert entry.agent == "Upset-Scorer"
    assert entry.run_id == "run-1"


async def test_chat_json_repairs_once_and_then_succeeds() -> None:
    def first(request_payload: Any) -> bool:
        return not _mentions(request_payload, "not valid JSON")

    transport = FixtureTransport()
    transport.add(
        lambda _method, _url, payload: first(payload),
        _response("not json at all"),
    )
    transport.add("/chat/completions", _response('{"ok": true}'))

    client = LlmClient(transport, base_url="https://arc.example", api_key="k")
    result = await client.chat_json(system=None, user="user", response_model=OkModel)
    assert result.ok is True
    assert len(transport.calls) == 2
    repair_payload = transport.calls[1].payload
    assert _mentions(repair_payload, "not valid JSON")


async def test_chat_json_raises_after_the_single_repair_fails() -> None:
    transport = FixtureTransport().add("/chat/completions", _response("still not json"))
    client = LlmClient(transport, base_url="https://arc.example", api_key="k")
    with pytest.raises(ContractError, match="not valid JSON"):
        await client.chat_json(system=None, user="user", response_model=OkModel)
    assert len(transport.calls) == 2


async def test_chat_json_honours_repair_false_and_extra_keys() -> None:
    transport = FixtureTransport().add(
        "/chat/completions", _response('{"ok": true, "unexpected": 1}')
    )
    client = LlmClient(transport, base_url="https://arc.example", api_key="k")
    with pytest.raises(ContractError, match="does not match"):
        await client.chat_json(system=None, user="user", response_model=OkModel, repair=False)
    assert len(transport.calls) == 1


async def test_chat_json_strips_markdown_fences() -> None:
    transport = FixtureTransport().add("/chat/completions", _response('```json\n{"ok": true}\n```'))
    client = LlmClient(transport, base_url="https://arc.example", api_key="k")
    result = await client.chat_json(system=None, user="user", response_model=OkModel)
    assert result.ok is True


async def test_reasoning_content_is_used_when_content_is_empty() -> None:
    payload = {
        "choices": [{"message": {"role": "assistant", "content": None, "reasoning": "hello"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    client = LlmClient(
        FixtureTransport().add("/chat/completions", payload),
        base_url="https://arc.example",
        api_key="k",
    )
    assert await client.chat_text(system=None, user="hi") == "hello"


async def test_non_200_and_missing_choices_are_typed_errors() -> None:
    client = LlmClient(
        FixtureTransport().add("/chat/completions", {"error": "auth"}, status_code=401),
        base_url="https://arc.example",
        api_key="k",
    )
    with pytest.raises(PermanentProviderError) as excinfo:
        await client.chat_text(system=None, user="hi")
    assert excinfo.value.status_code == 401

    client = LlmClient(
        FixtureTransport().add("/chat/completions", {"choices": []}),
        base_url="https://arc.example",
        api_key="k",
    )
    with pytest.raises(ContractError, match="no choices"):
        await client.chat_text(system=None, user="hi")


async def test_budget_exhaustion_is_raised_after_usage_is_recorded() -> None:
    budget = Budget(name="run", max_tokens=2)
    client = LlmClient(
        FixtureTransport().add("/chat/completions", _response("text", total_tokens=10)),
        base_url="https://arc.example",
        api_key="k",
        budget=budget,
    )
    with pytest.raises(BudgetExhausted):
        await client.chat_text(system=None, user="hi")
    assert budget.tokens_used == 10
    assert client.ledger.total_tokens == 10


def test_redacted_summary_never_contains_the_api_key() -> None:
    client = LlmClient(
        FixtureTransport(), base_url="https://arc.example", api_key="super-secret-key"
    )
    summary = client.redacted_summary()
    assert summary["api_key_configured"] is True
    assert "super-secret-key" not in json.dumps(summary)
    assert summary["ledger"]["calls"] == 0
