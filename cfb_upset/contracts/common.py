"""Shared contract primitives: strict models, UTC handling, provenance, citations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model for every inter-agent payload.

    ``extra="forbid"`` is deliberate: a typo in a handoff is a contract error,
    never silently dropped. The orchestrator translates the resulting
    ``ValidationError`` into a typed rejection reason.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(_require_aware_utc)]


class Citation(StrictModel):
    """A resolvable source supporting a claim or a rule."""

    citation_id: str | None = None
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    quote: str | None = None
    published_at: UTCDateTime | None = None
    source: str | None = None

    @field_validator("url")
    @classmethod
    def _url_has_scheme(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("citation URL must start with http:// or https://")
        return value


class Provenance(StrictModel):
    """Where a value came from and when it was knowable."""

    source: str
    source_url: str | None = None
    fetched_at: UTCDateTime | None = None
    published_at: UTCDateTime | None = None
    known_at: UTCDateTime
    content_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def dump_jsonable(model: BaseModel) -> dict[str, Any]:
    """Return a JSON-serialisable dict for tracing/schema tests."""

    return model.model_dump(mode="json")
