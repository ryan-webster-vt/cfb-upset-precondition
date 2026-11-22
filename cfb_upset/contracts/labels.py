"""Labeling, audit, and statistical-result contracts.

The deterministic labeler writes one ``LabeledGame`` per ``(game, spec,
version)`` with the evidence that produced the label. Statistical results keep
both raw p-values and FDR-adjusted q-values so the promotion decision can be
reproduced.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from cfb_upset.contracts.common import StrictModel, UTCDateTime
from cfb_upset.contracts.monitor import RuleEvidence, ScreenState


class DatasetSplit(str, Enum):
    """Chronological splits mandated by R25/R31."""

    DEV = "dev"
    VALIDATION = "validation"
    TEST = "test"


class Adjudication(str, Enum):
    """Blinded label-audit outcome (R30)."""

    HOLD = "HOLD"
    NOT_HOLD = "NOT_HOLD"
    UNKNOWN = "UNKNOWN"


class LabelEvidence(StrictModel):
    """The complete, canonical evidence trail for one label."""

    game_id: str = Field(min_length=1)
    spec_id: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    state: ScreenState
    evaluations: list[RuleEvidence] = Field(default_factory=list)
    known_at: UTCDateTime | None = None
    labeler_version: str = Field(min_length=1)
    note: str | None = None


class LabeledGame(StrictModel):
    """One deterministic label for one game/spec pair."""

    label_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    spec_id: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    label: int | None = Field(default=None, ge=0, le=1)
    evaluable: bool = True
    evidence: list[RuleEvidence] = Field(default_factory=list)
    labeler_version: str = Field(min_length=1)
    labeled_at: UTCDateTime

    @model_validator(mode="after")
    def _label_matches_evaluable(self) -> LabeledGame:
        if self.evaluable and self.label is None:
            raise ValueError("evaluable labels must be 0 or 1")
        if not self.evaluable and self.label is not None:
            raise ValueError("non-evaluable labels must have label=None")
        return self


class LabelAudit(StrictModel):
    """A sampled, blinded adjudication of one label."""

    audit_id: str = Field(min_length=1)
    spec_id: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    game_id: str = Field(min_length=1)
    sampled: bool = True
    adjudication: Adjudication
    evidence_ids: list[str] = Field(default_factory=list)
    quote: str | None = None
    auditor: str = Field(min_length=1)
    created_at: UTCDateTime


class StatResult(StrictModel):
    """Effect size, interval, and multiplicity-adjusted significance."""

    stat_id: str = Field(min_length=1)
    spec_id: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    split: DatasetSplit
    n: int = Field(ge=0)
    positives: int = Field(ge=0)
    risk_diff: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    odds_ratio: float | None = None
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    q_value: float | None = Field(default=None, ge=0.0, le=1.0)
    method: str = Field(min_length=1)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    computed_at: UTCDateTime

    @model_validator(mode="after")
    def _positives_within_n(self) -> StatResult:
        if self.positives > self.n:
            raise ValueError("positives cannot exceed n")
        return self
