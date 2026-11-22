"""Fetch adapter: URL safety, whitelist, text extraction, and snapshots.

The fetched bytes are stored verbatim in the content-addressed evidence store;
the model sees only the extracted text. A citation can therefore be re-read and
hash-verified even if the live page later changes.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from cfb_upset.adapters.search import domain_of, is_allowed
from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import FetchedPage
from cfb_upset.errors import PermanentProviderError
from cfb_upset.ids import Clock, SystemClock, sha256_hex
from cfb_upset.store.evidence import EvidenceStore


class FetchAdapter:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        allowed_domains: list[str] | None = None,
        evidence_store: EvidenceStore | None = None,
        clock: Clock | None = None,
        max_chars: int = 100_000,
    ) -> None:
        settings = get_settings()
        self.allowed_domains = allowed_domains or settings.allowed_domains
        self.evidence_store = evidence_store
        self.clock = clock or SystemClock()
        self.max_chars = max_chars
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(provider="fetch")
            self._owns_transport = True
        return self._transport

    async def fetch(
        self,
        url: str,
        *,
        published_at: datetime | None = None,
        kind: str = "article",
        title: str | None = None,
    ) -> FetchedPage:
        _validate_url(url, self.allowed_domains)
        response = await self._transport_or_default().get(url)
        if response.status_code != 200:
            raise PermanentProviderError(
                f"fetch: HTTP {response.status_code} for {domain_of(url)}",
                status_code=response.status_code,
                provider="fetch",
            )
        parser = _TextExtractor()
        parser.feed(response.text)
        text = parser.text()
        truncated = len(text) > self.max_chars
        if truncated:
            text = text[: self.max_chars].rstrip()
        fetched_at = self.clock.now()
        content_hash = sha256_hex(response.content)
        evidence_id: str | None = None
        snapshot_path: str | None = None
        if self.evidence_store is not None:
            snapshot = self.evidence_store.write(response.content, kind=kind, fetched_at=fetched_at)
            evidence_id = snapshot.evidence_id
            snapshot_path = snapshot.snapshot_path
        return FetchedPage(
            url=url,
            domain=domain_of(url),
            title=title or parser.title,
            text=text,
            status_code=response.status_code,
            fetched_at=fetched_at,
            published_at=published_at or parser.published_at,
            content_hash=content_hash,
            evidence_id=evidence_id,
            snapshot_path=snapshot_path,
            truncated=truncated,
        )


def _validate_url(url: str, allowed_domains: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PermanentProviderError(f"fetch: unsupported URL scheme {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise PermanentProviderError("fetch: URLs with embedded credentials are refused")
    host = parsed.hostname or ""
    if not host:
        raise PermanentProviderError("fetch: URL has no host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_reserved):
        raise PermanentProviderError("fetch: private/loopback IP literals are refused")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise PermanentProviderError("fetch: localhost is refused")
    if not is_allowed(url, allowed_domains):
        raise PermanentProviderError(f"fetch: domain {domain_of(url)!r} is not whitelisted")


class _TextExtractor(HTMLParser):
    """Small, dependency-free HTML-to-text extractor.

    It is deliberately conservative: script/style/noscript/svg content is
    dropped, block elements become newlines, and metadata timestamps are read
    from common article attributes.
    """

    _SKIP = {"script", "style", "noscript", "svg", "template"}
    _BLOCK = {
        "article",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._parts: list[str] = []
        self.title: str | None = None
        self.published_at: datetime | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value for key, value in attrs}
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK:
            self._parts.append("\n")
        if tag == "meta" and self.published_at is None:
            name = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).lower()
            if name in {
                "article:published_time",
                "og:published_time",
                "datepublished",
                "pubdate",
                "publish-date",
            }:
                self.published_at = _parse_datetime(attributes.get("content"))
        if tag == "time" and self.published_at is None:
            self.published_at = _parse_datetime(attributes.get("datetime"))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title = (self.title or "") + data.strip()
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["FetchAdapter"]
