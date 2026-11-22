"""Historical-corpus contracts.

These models are the Phase 1 handoff between the ``Data-Orchestrator``, its
``Historical-Stats Workers``, the Pydantic validation gate, and SQLite. Every
record carries field-level provenance so the ingestion path can prove that a
value was knowable before kickoff.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from cfb_upset.contracts.common import Provenance, StrictModel, UTCDateTime
from cfb_upset.contracts.slate import (
    GameStatus,
    OddsInfo,
    TeamInfo,
    VenueInfo,
    WeatherInfo,
)


class HistoricalGameRecord(StrictModel):
    """One completed or scheduled FBS-vs-FBS game in the historical corpus.

    ``home_score``/``away_score`` and ``team_stats`` are stored for labels and
    evaluation only. They are deliberately separate from ``field_provenance``
    so no feature builder can mistake a post-game value for a pre-kickoff one.
    """

    game_id: str = Field(min_length=1)
    season: int = Field(ge=1869, le=3000)
    week: int | None = Field(default=None, ge=0, le=30)
    season_type: int = 2
    kickoff_utc: UTCDateTime
    home: TeamInfo
    away: TeamInfo
    venue: VenueInfo | None = None
    neutral_site: bool = False
    conference_game: bool = False
    status: GameStatus = GameStatus.SCHEDULED
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    winner_team_id: str | None = None
    is_fbs_vs_fbs: bool = True
    odds: OddsInfo | None = None
    weather: WeatherInfo | None = None
    team_stats: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    field_provenance: dict[str, Provenance] = Field(default_factory=dict)
    source: str = "espn"
    fetched_at: UTCDateTime

    @model_validator(mode="after")
    def _winner_matches_a_team(self) -> HistoricalGameRecord:
        if self.winner_team_id is not None and self.winner_team_id not in {
            self.home.team_id,
            self.away.team_id,
        }:
            raise ValueError("winner_team_id must be the home or away team id")
        if self.home.team_id == self.away.team_id:
            raise ValueError("home and away team ids must differ")
        return self


class GameIdBatch(StrictModel):
    """A unit of work assigned to one Historical-Stats Worker."""

    batch_id: str = Field(min_length=1)
    game_ids: list[str] = Field(min_length=1)
    season: int | None = Field(default=None, ge=1869, le=3000)
    week: int | None = Field(default=None, ge=0, le=30)

    @model_validator(mode="after")
    def _unique_game_ids(self) -> GameIdBatch:
        if len(set(self.game_ids)) != len(self.game_ids):
            raise ValueError("game_ids must be unique within a batch")
        return self


class IngestReport(StrictModel):
    """Coverage and health summary returned by the Data-Orchestrator."""

    report_id: str = Field(min_length=1)
    seasons: list[int] = Field(default_factory=list)
    games_requested: int = Field(default=0, ge=0)
    games_stored: int = Field(default=0, ge=0)
    duplicates_removed: int = Field(default=0, ge=0)
    quarantined: int = Field(default=0, ge=0)
    coverage: dict[str, Any] = Field(default_factory=dict)
    source: str = "espn"
    started_at: UTCDateTime
    finished_at: UTCDateTime

    @model_validator(mode="after")
    def _counts_are_sane(self) -> IngestReport:
        if self.games_stored + self.quarantined > self.games_requested:
            raise ValueError("stored + quarantined cannot exceed games_requested")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class QuarantineRecord(StrictModel):
    """A record that failed validation, preserved with the exact errors."""

    record_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(min_length=1)
    source: str = "espn"
    created_at: UTCDateTime
