"""Scoring and run-result contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from cfb_upset.contracts.common import Citation, StrictModel, UTCDateTime
from cfb_upset.contracts.monitor import AgentEvent, MatchedSpec, ScreenMatch
from cfb_upset.contracts.slate import SlateGame


class ScoreBackend(str, Enum):
    D3_MINI = "d3_mini"
    CALIBRATED_RULES = "calibrated_rules"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    NO_PRECONDITIONS_MATCHED = "no_preconditions_matched"
    NO_QUALIFYING_FLAGS = "no_qualifying_flags"
    DEGRADED = "degraded"
    FAILED = "failed"


class UpsetScore(StrictModel):
    """A calibrated-ish upset probability plus the evidence behind it.

    Phase 0 uses a deterministic rule-count/base-rate stub. Later phases keep
    this exact contract while swapping in the ``d3_mini`` or fitted
    ``calibrated_rules`` backend.
    """

    game_id: str
    probability: float = Field(ge=0.0, le=1.0)
    raw_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    key_signals: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    backend: ScoreBackend
    model_version: str
    rationale: str
    unstable: bool = False
    degraded_reason: str | None = None
    score_value: float | None = None
    score_legend: dict[str, str] | None = None


class RankedAlert(StrictModel):
    rank: int = Field(ge=1)
    game: SlateGame
    score: UpsetScore
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    matched_specs: list[MatchedSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _score_belongs_to_game(self) -> RankedAlert:
        if self.score.game_id != self.game.game_id:
            raise ValueError("score.game_id must match game.game_id")
        return self


class RunResult(StrictModel):
    run_id: str
    slate_date: Any  # datetime.date; kept as Any to avoid an import cycle in schema
    status: RunStatus
    alerts: list[RankedAlert] = Field(default_factory=list)
    matches: list[ScreenMatch] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    degraded: bool = False
    reason: str | None = None
    started_at: UTCDateTime
    finished_at: UTCDateTime


class ScoreRequest(StrictModel):
    """Everything the Upset-Scorer is allowed to see for one game.

    Post-kickoff evidence is removed by the monitor payload builder before this
    model is constructed; the request itself contains only admitted values.
    """

    request_id: str = Field(min_length=1)
    game: SlateGame
    matched_specs: list[MatchedSpec] = Field(default_factory=list)
    market_prob: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: UTCDateTime


class CacheEntry(StrictModel):
    """A replayable analysis-cache record with a versioned key."""

    cache_key: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    spec_set_hash: str = Field(min_length=1)
    evidence_hash: str = Field(min_length=1)
    scorer_version: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    result_json: dict[str, Any] = Field(default_factory=dict)
    created_at: UTCDateTime
    expires_at: UTCDateTime | None = None
