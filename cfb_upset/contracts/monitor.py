"""Monitoring-side contracts: rule evidence, screen matches, and agent events."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from cfb_upset.contracts.common import StrictModel, UTCDateTime
from cfb_upset.contracts.spec import RuleOp


class ScreenState(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class RuleEvidence(StrictModel):
    """Why a rule fired (or did not), including the observed value and timestamp."""

    field: str
    op: RuleOp
    threshold: Any = None
    value2: Any = None
    observed: Any = None
    units: str | None = None
    state: ScreenState
    known_at: UTCDateTime | None = None
    note: str | None = None


class MatchedSpec(StrictModel):
    spec_id: str
    version: int = Field(ge=1)
    title: str
    evidence: RuleEvidence


class ScreenMatch(StrictModel):
    game_id: str
    matched_specs: list[MatchedSpec] = Field(default_factory=list)
    matched_count: int = Field(ge=0)
    evaluable_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)

    @field_validator("matched_specs")
    @classmethod
    def _no_duplicate_specs(cls, value: list[MatchedSpec]) -> list[MatchedSpec]:
        seen: set[str] = set()
        for match in value:
            if match.spec_id in seen:
                raise ValueError(f"duplicate matched spec_id {match.spec_id!r}")
            seen.add(match.spec_id)
        return value

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> ScreenMatch:
        if self.matched_count != len(self.matched_specs):
            raise ValueError("matched_count must equal len(matched_specs)")
        if self.matched_count > self.evaluable_count:
            raise ValueError("matched_count cannot exceed evaluable_count")
        return self


class AgentEvent(StrictModel):
    """A single timeline event; the UI renders these in order."""

    event_id: str
    run_id: str
    agent: str
    phase: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: UTCDateTime
