"""Fault-tolerant async HTTP client.

One client per provider. It adds timeouts, bounded retries with jitter, honour
of ``Retry-After``/``retry_after_s``, and a circuit breaker. Adapters wrap this
client; agents only see typed errors.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from cfb_upset.errors import PermanentProviderError, TransientProviderError

SleepFn = Callable[[float], Awaitable[None]]


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_backoff_s: float = 0.5
    max_backoff_s: float = 8.0
    jitter_s: float = 0.25


class CircuitBreaker:
    """Per-provider breaker: open after N consecutive failures for a cool-down."""

    def __init__(self, *, failure_threshold: int = 5, reset_timeout_s: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if (time.monotonic() - self._opened_at) >= self.reset_timeout_s:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def allow(self) -> bool:
        return not self.is_open

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()


class HttpClient:
    """Thin async HTTP wrapper with retry and circuit-breaker semantics."""

    def __init__(
        self,
        *,
        base_url: str = "",
        provider: str = "http",
        timeout_s: float = 20.0,
        retry: RetryConfig | None = None,
        breaker: CircuitBreaker | None = None,
        headers: dict[str, str] | None = None,
        sleep: SleepFn = asyncio.sleep,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = provider
        self.retry = retry or RetryConfig()
        self.breaker = breaker or CircuitBreaker()
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s),
            headers=headers or {},
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
        timeout_s: float | None = None,
    ) -> httpx.Response:
        """Perform one request, retrying transient failures.

        Raises:
            TransientProviderError: retries exhausted, timeout, transport error,
                or an open circuit.
            PermanentProviderError: non-retryable 4xx.
        """

        if not self.breaker.allow():
            raise TransientProviderError(
                f"{self.provider}: circuit breaker open after repeated failures",
                provider=self.provider,
            )

        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    content=content,
                    timeout=httpx.Timeout(timeout_s) if timeout_s is not None else None,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                self.breaker.record_failure()
                if attempt >= self.retry.max_attempts:
                    raise TransientProviderError(
                        f"{self.provider}: {type(exc).__name__} after {attempt} attempts",
                        provider=self.provider,
                    ) from exc
                await self._sleep(self._backoff(attempt))
                continue

            if 200 <= response.status_code < 300:
                self.breaker.record_success()
                return response

            retry_after = _retry_after_seconds(response)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                self.breaker.record_failure()
                if attempt >= self.retry.max_attempts:
                    raise TransientProviderError(
                        f"{self.provider}: HTTP {response.status_code} after {attempt} attempts",
                        status_code=response.status_code,
                        provider=self.provider,
                        retry_after_s=retry_after,
                    ) from None
                await self._sleep(
                    retry_after if retry_after is not None else self._backoff(attempt)
                )
                continue

            raise PermanentProviderError(
                f"{self.provider}: HTTP {response.status_code}",
                status_code=response.status_code,
                provider=self.provider,
            )

        raise TransientProviderError(  # pragma: no cover - loop always returns/raises
            f"{self.provider}: retries exhausted ({last_error!r})",
            provider=self.provider,
        )

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.request("GET", url, params=params, headers=headers)
        return response.json()

    async def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> Any:
        response = await self.request(
            "POST",
            url,
            json_body=payload,
            headers=headers,
            timeout_s=timeout_s,
        )
        return response.json()

    def _backoff(self, attempt: int) -> float:
        delay = min(self.retry.max_backoff_s, self.retry.base_backoff_s * (2 ** (attempt - 1)))
        return delay + random.uniform(0.0, self.retry.jitter_s)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read retry-after from the header first, then the JSON body."""

    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(payload, dict):
        candidates = [
            payload.get("retry_after_s"),
            payload.get("retry_after"),
            (
                payload.get("error", {}).get("retry_after_s")
                if isinstance(payload.get("error"), dict)
                else None
            ),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                return max(0.0, float(candidate))
            except (TypeError, ValueError):
                continue
    return None
