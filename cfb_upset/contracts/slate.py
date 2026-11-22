"""Slate-side contracts: teams, venues, odds, weather, and games."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import Field

from cfb_upset.contracts.common import Provenance, StrictModel, UTCDateTime


class GameStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELED = "canceled"


class FavoriteSource(str, Enum):
    CFBD_OPEN = "cfbd_open"
    ESPN_OPEN = "espn_open"
    STRENGTH_PROXY = "strength_proxy"


class MarketProbSource(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD_MAPPED = "spread_mapped"
    UNAVAILABLE = "unavailable"


class TeamInfo(StrictModel):
    team_id: str = Field(min_length=1)
    school: str = Field(min_length=1)
    nickname: str | None = None
    abbreviation: str | None = None
    conference: str | None = None
    is_fbs: bool = True
    color: str | None = None
    alt_color: str | None = None
    logo_url: str | None = None
    rank: int | None = Field(default=None, ge=1, le=25)
    record: str | None = None


class VenueInfo(StrictModel):
    venue_id: str | None = None
    name: str = Field(min_length=1)
    city: str | None = None
    state: str | None = None
    country: str | None = None
    indoor: bool | None = None
    grass: bool | None = None
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    altitude_m: float | None = None
    tz: str | None = None
    source: str | None = None


class OddsInfo(StrictModel):
    """Pre-kickoff market context.

    ``spread`` is from the favourite's perspective (negative = favourite gives
    points). Opening/closing distinction is carried by ``known_at`` so the
    leakage filter can exclude anything known at or after kickoff.
    """

    provider: str | None = None
    favorite_team_id: str | None = None
    spread: float | None = None
    spread_open: float | None = None
    over_under: float | None = None
    market_prob: float | None = Field(default=None, ge=0.0, le=1.0)
    favorite_source: FavoriteSource
    line_provider: str | None = None
    market_prob_source: MarketProbSource = MarketProbSource.UNAVAILABLE
    known_at: UTCDateTime


class WeatherInfo(StrictModel):
    temperature_c: float | None = None
    wind_kph: float | None = Field(default=None, ge=0.0)
    precipitation_mm: float | None = Field(default=None, ge=0.0)
    condition: str | None = None
    source: str | None = None
    known_at: UTCDateTime | None = None
    lead_hours: float | None = Field(default=None, ge=0.0, le=168.0)
    unavailable_reason: str | None = None


class SlateGame(StrictModel):
    """One FBS-vs-FBS game shown to the user and screened by the agents."""

    game_id: str = Field(min_length=1)
    slate_date: date
    kickoff_utc: UTCDateTime
    home: TeamInfo
    away: TeamInfo
    venue: VenueInfo | None = None
    neutral_site: bool = False
    conference_game: bool = False
    status: GameStatus = GameStatus.SCHEDULED
    odds: OddsInfo | None = None
    weather: WeatherInfo | None = None
    broadcast: str | None = None
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.away.school} at {self.home.school}"
