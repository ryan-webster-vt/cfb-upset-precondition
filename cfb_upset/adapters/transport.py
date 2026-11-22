"""Provider transport abstraction.

Adapters talk to a tiny ``Transport`` protocol instead of an HTTP library. In
production ``HttpTransport`` adds the P0 retry/circuit-breaker client; in tests
``FixtureTransport`` replays captured JSON or HTML with zero network access.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cfb_upset.adapters.http import HttpClient, RetryConfig

Matcher = str | Callable[[str, str, Any], bool]


@dataclass(frozen=True)
class TransportResponse:
    """A provider response normalised across HTTP and fixtures."""

    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    url: str = ""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)

    def raise_for_status(self) -> TransportResponse:
        if not 200 <= self.status_code < 300:
            raise ValueError(f"provider returned HTTP {self.status_code}")
        return self


@runtime_checkable
class Transport(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse: ...

    async def post(
        self,
        url: str,
        *,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse: ...


class HttpTransport:
    """Production transport backed by the P0 fault-tolerant ``HttpClient``."""

    def __init__(
        self,
        *,
        base_url: str = "",
        provider: str = "http",
        timeout_s: float = 20.0,
        retry: RetryConfig | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.provider = provider
        self.client = HttpClient(
            base_url=base_url,
            provider=provider,
            timeout_s=timeout_s,
            retry=retry,
            headers=headers,
        )

    async def __aenter__(self) -> HttpTransport:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse:
        response = await self.client.request("GET", url, params=params, headers=headers)
        return TransportResponse(
            status_code=response.status_code,
            content=response.content,
            headers=dict(response.headers),
            url=str(response.url),
        )

    async def post(
        self,
        url: str,
        *,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse:
        response = await self.client.request("POST", url, json_body=payload, headers=headers)
        return TransportResponse(
            status_code=response.status_code,
            content=response.content,
            headers=dict(response.headers),
            url=str(response.url),
        )


@dataclass(frozen=True)
class FixtureCall:
    method: str
    url: str
    payload: Any = None


class FixtureTransport:
    """Deterministic transport that replays recorded payloads.

    A matcher is either a substring of the requested URL (evaluation order is
    insertion order) or a predicate over ``(method, url, payload)``. Any
    unmatched request returns a synthetic 404 so a test fails at the parse
    boundary instead of hanging on a network call.
    """

    def __init__(self) -> None:
        self._routes: list[tuple[Matcher, TransportResponse]] = []
        self.calls: list[FixtureCall] = []

    def add(
        self,
        matcher: Matcher,
        payload: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> FixtureTransport:
        self._routes.append((matcher, _to_response(payload, status_code, headers)))
        return self

    def add_file(
        self,
        matcher: Matcher,
        path: str | Path,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> FixtureTransport:
        return self.add(matcher, Path(path).read_bytes(), status_code=status_code, headers=headers)

    def add_json_file(
        self,
        matcher: Matcher,
        path: str | Path,
        *,
        status_code: int = 200,
    ) -> FixtureTransport:
        return self.add(
            matcher,
            json.loads(Path(path).read_text(encoding="utf-8")),
            status_code=status_code,
            headers={"content-type": "application/json"},
        )

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse:
        full_url = _with_params(url, params)
        self.calls.append(FixtureCall("GET", full_url))
        return self._resolve("GET", full_url, None)

    async def post(
        self,
        url: str,
        *,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse:
        self.calls.append(FixtureCall("POST", url, payload))
        return self._resolve("POST", url, payload)

    def _resolve(self, method: str, url: str, payload: Any) -> TransportResponse:
        for matcher, response in self._routes:
            if callable(matcher):
                matched = matcher(method, url, payload)
            else:
                matched = matcher in url
            if matched:
                return TransportResponse(
                    status_code=response.status_code,
                    content=response.content,
                    headers=response.headers,
                    url=url,
                )
        return TransportResponse(
            status_code=404,
            content=json.dumps({"error": "fixture not found", "url": url}).encode(),
            headers={"content-type": "application/json"},
            url=url,
        )


def _to_response(
    payload: Any,
    status_code: int,
    headers: dict[str, str] | None,
) -> TransportResponse:
    if isinstance(payload, TransportResponse):
        return payload
    if isinstance(payload, bytes | bytearray):
        content = bytes(payload)
    elif isinstance(payload, str):
        content = payload.encode("utf-8")
    else:
        content = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json", **(headers or {})}
    return TransportResponse(status_code=status_code, content=content, headers=headers or {})


def _with_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    from urllib.parse import urlencode

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params, doseq=True)}"


__all__ = [
    "FixtureTransport",
    "HttpTransport",
    "Transport",
    "TransportResponse",
]
