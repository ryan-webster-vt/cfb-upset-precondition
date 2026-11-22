"""Monitoring-side contracts: rule evidence, screen matches, and agent events."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from cfb_upset.contracts.common import StrictModel, UTCDateTime
from cfb_upset.contracts.slate import SlateGame
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


class MonitorDecisionType(str, Enum):
    """The decision-model answer for one game's matched-rule bundle."""

    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class MonitorTask(StrictModel):
    """One game assigned to exactly one Monitor Worker."""

    task_id: str = Field(min_length=1)
    game: SlateGame
    matched_specs: list[MatchedSpec] = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    worker_id: str = Field(min_length=1)


class MonitorDecision(StrictModel):
    """A worker's confirm/drop result with probabilities and evidence refs.

    ``dissent`` preserves minority signals (Pr9) instead of collapsing every
    disagreement into a confident answer.
    """

    game_id: str = Field(min_length=1)
    decision: MonitorDecisionType
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    quotes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    dissent: list[str] = Field(default_factory=list)
    created_at: UTCDateTime

    @field_validator("probabilities")
    @classmethod
    def _probabilities_are_bounded(cls, value: dict[str, float]) -> dict[str, float]:
        for name, probability in value.items():
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probability for {name!r} must be in [0, 1]")
        return value

    @model_validator(mode="after")
    def _confirmed_requires_evidence(self) -> MonitorDecision:
        if self.decision is MonitorDecisionType.CONFIRMED:
            if not self.evidence_ids:
                raise ValueError("a confirmed decision requires at least one evidence_id")
            if not self.quotes and not self.rationale:
                raise ValueError("a confirmed decision requires a quote or rationale")
        return self


class ConfirmedFlag(StrictModel):
    """A confirmed upset flag handed from the monitor to the scorer."""

    game_id: str = Field(min_length=1)
    matched_specs: list[MatchedSpec] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    decision: MonitorDecision
    confirmed_at: UTCDateTime

    @model_validator(mode="after")
    def _decision_is_confirmed_and_same_game(self) -> ConfirmedFlag:
        if self.decision.decision is not MonitorDecisionType.CONFIRMED:
            raise ValueError("ConfirmedFlag requires a confirmed decision")
        if self.decision.game_id != self.game_id:
            raise ValueError("decision.game_id must match flag.game_id")
        return self
