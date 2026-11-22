"""Search adapter (Brave) with a configurable domain whitelist."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import SearchHit
from cfb_upset.ids import Clock, SystemClock

logger = logging.getLogger(__name__)


class SearchAdapter:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        allowed_domains: list[str] | None = None,
        clock: Clock | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.brave_key
        self.base_url = (base_url or settings.brave_base_url).rstrip("/")
        self.allowed_domains = allowed_domains or settings.allowed_domains
        self.clock = clock or SystemClock()
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider="brave")
            self._owns_transport = True
        return self._transport

    async def search(self, query: str, *, count: int = 5) -> list[SearchHit]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Subscription-Token"] = self.api_key
        response = await self._transport_or_default().get(
            f"{self.base_url}/web/search",
            params={"q": query, "count": count},
            headers=headers,
        )
        response.raise_for_status()
        return self.parse(response.json())

    def parse(self, payload: dict[str, Any]) -> list[SearchHit]:
        raw_results = (payload.get("web") or {}).get("results") or payload.get("results") or []
        hits: list[SearchHit] = []
        for item in raw_results:
            url = item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            domain = domain_of(url)
            if not is_allowed(url, self.allowed_domains):
                logger.info("search: dropping non-whitelisted domain %s", domain)
                continue
            hits.append(
                SearchHit(
                    title=str(title),
                    url=str(url),
                    description=item.get("description"),
                    domain=domain,
                    age=item.get("age"),
                    published_at=_parse_datetime(
                        item.get("page_age") or item.get("published_at") or item.get("age")
                    ),
                )
            )
        return hits


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_allowed(url: str, allowed_domains: list[str]) -> bool:
    host = domain_of(url)
    if not host:
        return False
    for domain in allowed_domains:
        candidate = domain.lower().lstrip(".").removeprefix("www.")
        if host == candidate or host.endswith(f".{candidate}"):
            return True
    return False


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["SearchAdapter", "domain_of", "is_allowed"]
