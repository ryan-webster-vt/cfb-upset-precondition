"""Tool-adapter result contracts.

These are not inter-agent handoffs in the strictest sense, but they cross the
adapter/agent boundary. Keeping them strict means a malformed provider response
fails at the adapter instead of leaking an untyped dictionary into a prompt.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from cfb_upset.contracts.common import StrictModel, UTCDateTime


class SearchHit(StrictModel):
    """One whitelisted web-search result."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    description: str | None = None
    domain: str = Field(min_length=1)
    age: str | None = None
    published_at: UTCDateTime | None = None

    @field_validator("url")
    @classmethod
    def _url_has_scheme(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("search result URL must start with http:// or https://")
        return value


class FetchedPage(StrictModel):
    """A fetched, text-extracted page with provenance and optional snapshot."""

    url: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    title: str | None = None
    text: str
    status_code: int = Field(default=200, ge=100, le=599)
    fetched_at: UTCDateTime
    published_at: UTCDateTime | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    evidence_id: str | None = None
    snapshot_path: str | None = None
    truncated: bool = False
