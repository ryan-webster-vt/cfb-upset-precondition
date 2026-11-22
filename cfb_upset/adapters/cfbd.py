"""CollegeFootballData (CFBD) adapter: open lines and venue geodata.

CFBD is the primary historical odds source because it exposes ``spreadOpen``,
and the primary venue source because ESPN carries no lat/lon. The 2021 sample
shows 75.9% null ``spreadOpen``, so ``pick_odds`` returns ``None`` rather than
pretending a closing line was an open; Phase 3 then falls back to ESPN or a
strength proxy and records the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import FavoriteSource, MarketProbSource, OddsInfo, VenueInfo
from cfb_upset.domain.leakage import derive_known_at
from cfb_upset.ids import Clock, SystemClock


@dataclass(frozen=True)
class CfbdLine:
    provider: str
    spread: float | None = None
    spread_open: float | None = None
    over_under: float | None = None
    over_under_open: float | None = None
    home_moneyline: float | None = None
    away_moneyline: float | None = None


@dataclass(frozen=True)
class CfbdGameLines:
    game_id: str
    season: int
    week: int | None
    home_team: str
    away_team: str
    home_classification: str | None = None
    away_classification: str | None = None
    lines: list[CfbdLine] = field(default_factory=list)

    @property
    def is_fbs_vs_fbs(self) -> bool:
        return (self.home_classification or "").lower() == "fbs" and (
            self.away_classification or ""
        ).lower() == "fbs"


class CfbdAdapter:
    """Typed CFBD client with fixture replay and optional API key."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        clock: Clock | None = None,
        line_providers: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.cfbd_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.cfbd_key
        self.clock = clock or SystemClock()
        self.line_providers = line_providers or settings.cfbd_line_providers
        self._transport = transport
        self._owns_transport = transport is None

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider="cfbd")
            self._owns_transport = True
        return self._transport

    async def fetch_lines(
        self,
        *,
        season: int,
        week: int | None = None,
        season_type: str = "regular",
        team: str | None = None,
    ) -> list[CfbdGameLines]:
        params: dict[str, Any] = {"year": season, "seasonType": season_type}
        if week is not None:
            params["week"] = week
        if team is not None:
            params["team"] = team
        response = await self._transport_or_default().get(
            "/lines", params=params, headers=self._headers()
        )
        response.raise_for_status()
        return self.parse_lines(response.json())

    async def fetch_venues(self) -> list[VenueInfo]:
        response = await self._transport_or_default().get("/venues", headers=self._headers())
        response.raise_for_status()
        return self.parse_venues(response.json())

    # ------------------------------------------------------------------ parsers
    @staticmethod
    def parse_lines(payload: list[dict[str, Any]]) -> list[CfbdGameLines]:
        games: list[CfbdGameLines] = []
        for raw in payload:
            lines = [
                CfbdLine(
                    provider=str(line.get("provider") or ""),
                    spread=_optional_float(line.get("spread")),
                    spread_open=_optional_float(line.get("spreadOpen")),
                    over_under=_optional_float(line.get("overUnder")),
                    over_under_open=_optional_float(line.get("overUnderOpen")),
                    home_moneyline=_optional_float(line.get("homeMoneyline")),
                    away_moneyline=_optional_float(line.get("awayMoneyline")),
                )
                for line in raw.get("lines", [])
            ]
            games.append(
                CfbdGameLines(
                    game_id=str(raw.get("id")),
                    season=int(raw.get("season") or 0),
                    week=raw.get("week"),
                    home_team=str(raw.get("homeTeam") or ""),
                    away_team=str(raw.get("awayTeam") or ""),
                    home_classification=raw.get("homeClassification"),
                    away_classification=raw.get("awayClassification"),
                    lines=lines,
                )
            )
        return games

    @staticmethod
    def parse_venues(payload: list[dict[str, Any]]) -> list[VenueInfo]:
        venues: list[VenueInfo] = []
        for raw in payload:
            name = raw.get("name")
            if not name:
                continue
            venues.append(
                VenueInfo(
                    venue_id=str(raw["id"]) if raw.get("id") is not None else None,
                    name=str(name),
                    city=_optional_str(raw.get("city")),
                    state=_optional_str(raw.get("state")),
                    country=_optional_str(raw.get("countryCode")),
                    indoor=raw.get("dome"),
                    grass=raw.get("grass"),
                    lat=_optional_float(raw.get("latitude")),
                    lon=_optional_float(raw.get("longitude")),
                    altitude_m=_optional_float(raw.get("elevation")),
                    tz=_optional_str(raw.get("timezone")),
                    source="cfbd",
                )
            )
        return venues

    def pick_odds(
        self,
        game: CfbdGameLines,
        *,
        home_team_id: str,
        away_team_id: str,
        kickoff: datetime,
    ) -> OddsInfo | None:
        """Pick the configured provider's open line, or return ``None``.

        Returning ``None`` is meaningful: Phase 3 records
        ``favorite_source=strength_proxy`` instead of silently substituting a
        closing spread for an open one.
        """

        preferred = [_normalize_provider(name) for name in self.line_providers]
        candidates: list[CfbdLine] = []
        for provider in preferred:
            for line in game.lines:
                if line.spread_open is not None and provider in _normalize_provider(line.provider):
                    candidates.append(line)
                    break
        if not candidates:
            return None
        line = candidates[0]
        assert line.spread_open is not None
        favorite_is_home = line.spread_open <= 0
        favorite_team_id = home_team_id if favorite_is_home else away_team_id
        market_prob, prob_source = _moneyline_probability(line, favorite_is_home)
        return OddsInfo(
            provider=line.provider,
            favorite_team_id=favorite_team_id,
            spread=-abs(line.spread) if line.spread is not None else None,
            spread_open=-abs(line.spread_open),
            over_under=(
                line.over_under_open if line.over_under_open is not None else line.over_under
            ),
            market_prob=market_prob,
            favorite_source=FavoriteSource.CFBD_OPEN,
            line_provider=line.provider,
            market_prob_source=prob_source,
            known_at=derive_known_at("spread_open", kickoff),
        )


def _normalize_provider(value: str) -> str:
    """Normalise ``ESPN_BET`` and ``ESPN Bet`` to one comparable form."""

    return " ".join(value.replace("_", " ").lower().split())


def american_to_probability(american: float) -> float:
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _moneyline_probability(
    line: CfbdLine,
    favorite_is_home: bool,
) -> tuple[float | None, MarketProbSource]:
    if line.home_moneyline is None or line.away_moneyline is None:
        return None, MarketProbSource.UNAVAILABLE
    home_prob = american_to_probability(line.home_moneyline)
    away_prob = american_to_probability(line.away_moneyline)
    total = home_prob + away_prob
    if total <= 0:
        return None, MarketProbSource.UNAVAILABLE
    no_vig_home = home_prob / total
    return (no_vig_home if favorite_is_home else 1.0 - no_vig_home), MarketProbSource.MONEYLINE


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["CfbdAdapter", "CfbdGameLines", "CfbdLine", "american_to_probability"]
