"""ESPN adapter: scoreboard, summary, core odds, rankings, and groups.

The parse functions are pure so the Phase 2 orchestrator can replay a captured
payload without a transport. Every schedule field gets a conservative
``kickoff - 7d`` provenance stamp; box scores are stamped at kickoff and are
therefore excluded by the leakage filter (labels only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import (
    FavoriteSource,
    GameStatus,
    HistoricalGameRecord,
    MarketProbSource,
    OddsInfo,
    Provenance,
    TeamInfo,
    VenueInfo,
)
from cfb_upset.domain.leakage import derive_known_at
from cfb_upset.ids import Clock, SystemClock

FBS_GROUP_ID = "80"


@dataclass(frozen=True)
class Rankings:
    season: int
    week: int | None
    poll: str
    ranks: dict[str, int]
    published_at: datetime | None
    week_earliest_kickoff: datetime | None = None


@dataclass(frozen=True)
class GroupInfo:
    group_id: str
    name: str
    parent_id: str | None
    team_ids: list[str] = field(default_factory=list)


class EspnAdapter:
    """Typed, fixture-friendly ESPN site + core API client."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        base_url: str | None = None,
        core_base_url: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.espn_api_base_url).rstrip("/")
        self.core_base_url = (core_base_url or settings.espn_core_base_url).rstrip("/")
        self.clock = clock or SystemClock()
        self._transport = transport
        self._owns_transport = transport is None

    async def __aenter__(self) -> EspnAdapter:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport and isinstance(self._transport, HttpTransport):
            await self._transport.aclose()

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider="espn")
            self._owns_transport = True
        return self._transport

    async def fetch_scoreboard(
        self,
        *,
        dates: date | str | None = None,
        week: int | None = None,
        season_type: int | None = None,
        limit: int = 200,
    ) -> list[HistoricalGameRecord]:
        params: dict[str, Any] = {"limit": limit}
        if dates is not None:
            params["dates"] = dates.strftime("%Y%m%d") if isinstance(dates, date) else dates
        if week is not None:
            params["week"] = week
        if season_type is not None:
            params["seasontype"] = season_type
        response = await self._transport_or_default().get("/scoreboard", params=params)
        response.raise_for_status()
        return self.parse_scoreboard(response.json(), fetched_at=self.clock.now())

    async def fetch_summary(self, game_id: str) -> HistoricalGameRecord:
        response = await self._transport_or_default().get("/summary", params={"event": game_id})
        response.raise_for_status()
        return self.parse_summary(response.json(), fetched_at=self.clock.now())

    async def fetch_odds(self, game_id: str) -> list[dict[str, Any]]:
        url = f"{self.core_base_url}/events/{game_id}/competitions/{game_id}/odds"
        response = await self._transport_or_default().get(url, params={"limit": 20})
        response.raise_for_status()
        payload = response.json()
        return payload.get("items", [])

    async def fetch_rankings(
        self,
        *,
        season: int,
        week: int | None = None,
        season_type: int = 2,
    ) -> Rankings:
        params: dict[str, Any] = {"season": season, "seasontype": season_type}
        if week is not None:
            params["week"] = week
        response = await self._transport_or_default().get("/rankings", params=params)
        response.raise_for_status()
        return self.parse_rankings(response.json())

    async def fetch_groups(self, *, season: int | None = None) -> list[GroupInfo]:
        params = {"season": season} if season is not None else None
        response = await self._transport_or_default().get("/groups", params=params)
        response.raise_for_status()
        return self.parse_groups(response.json())

    # ------------------------------------------------------------------ parsers
    def parse_scoreboard(
        self,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> list[HistoricalGameRecord]:
        stamp = fetched_at or self.clock.now()
        records: list[HistoricalGameRecord] = []
        for event in payload.get("events", []):
            competition = _first(event.get("competitions"))
            if competition is None:
                continue
            record = self._scoreboard_record(event, competition, stamp)
            if record is not None:
                records.append(record)
        return records

    def _scoreboard_record(
        self,
        event: dict[str, Any],
        competition: dict[str, Any],
        fetched_at: datetime,
    ) -> HistoricalGameRecord | None:
        kickoff = _parse_datetime(competition.get("date") or event.get("date"))
        if kickoff is None:
            return None
        competitors = competition.get("competitors", [])
        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if home is None or away is None:
            return None
        status = _status(competition.get("status") or event.get("status"))
        home_team = _team_info(home)
        away_team = _team_info(away)
        if home_team is None or away_team is None:
            return None
        venue = _venue_info(competition.get("venue"))
        scores = _scores(home, away, status)
        season = int((event.get("season") or {}).get("year") or _season_from_date(kickoff))
        week = (event.get("week") or {}).get("number")
        season_type = int((event.get("season") or {}).get("type") or 2)
        source_url = f"{self.base_url}/scoreboard"
        odds = self.parse_odds(
            competition.get("odds") or [],
            home_team_id=home_team.team_id,
            away_team_id=away_team.team_id,
            kickoff=kickoff,
            fetched_at=fetched_at,
        )
        provenance = _provenance(
            source="espn",
            source_url=source_url,
            fetched_at=fetched_at,
            kickoff=kickoff,
            fields={
                "game_id": "schedule",
                "season": "schedule",
                "week": "schedule",
                "season_type": "schedule",
                "kickoff_utc": "schedule",
                "home": "team_identity",
                "away": "team_identity",
                "venue": "venue",
                "neutral_site": "schedule",
                "conference_game": "schedule",
                "status": "schedule",
                "odds": "opening_odds",
                "home_score": None,
                "away_score": None,
                "winner_team_id": None,
            },
        )
        return HistoricalGameRecord(
            game_id=str(event.get("id") or competition.get("id")),
            season=season,
            week=week,
            season_type=season_type,
            kickoff_utc=kickoff,
            home=home_team,
            away=away_team,
            venue=venue,
            neutral_site=bool(competition.get("neutralSite")),
            conference_game=bool(competition.get("conferenceCompetition")),
            status=status,
            home_score=scores[0],
            away_score=scores[1],
            winner_team_id=_winner_team_id(home, away, status),
            is_fbs_vs_fbs=True,
            odds=odds,
            weather=None,
            field_provenance=provenance,
            source="espn",
            fetched_at=fetched_at,
        )

    def parse_summary(
        self,
        payload: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> HistoricalGameRecord:
        stamp = fetched_at or self.clock.now()
        header = payload.get("header", {})
        competition = _first(header.get("competitions"))
        if competition is None:
            raise ValueError("ESPN summary has no header competition")
        event_id = str(header.get("id") or competition.get("id"))
        kickoff = _parse_datetime(competition.get("date"))
        if kickoff is None:
            raise ValueError("ESPN summary has no kickoff date")
        competitors = competition.get("competitors", [])
        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if home is None or away is None:
            raise ValueError("ESPN summary is missing a home or away competitor")
        home_team = _team_info(home)
        away_team = _team_info(away)
        if home_team is None or away_team is None:
            raise ValueError("ESPN summary is missing team identity")
        status = _status(competition.get("status") or header.get("status"))
        venue = _venue_info((payload.get("gameInfo") or {}).get("venue"))
        scores = _scores(home, away, status)
        season = int((header.get("season") or {}).get("year") or _season_from_date(kickoff))
        week = header.get("week")
        season_type = int((header.get("season") or {}).get("type") or 2)
        team_stats = _team_stats(payload.get("boxscore") or {})
        source_url = f"{self.base_url}/summary?event={event_id}"
        provenance = _provenance(
            source="espn",
            source_url=source_url,
            fetched_at=stamp,
            kickoff=kickoff,
            fields={
                "game_id": "schedule",
                "season": "schedule",
                "week": "schedule",
                "season_type": "schedule",
                "kickoff_utc": "schedule",
                "home": "team_identity",
                "away": "team_identity",
                "venue": "venue",
                "neutral_site": "schedule",
                "conference_game": "schedule",
                "status": "schedule",
                "home_score": None,
                "away_score": None,
                "winner_team_id": None,
                "team_stats": None,
            },
        )
        return HistoricalGameRecord(
            game_id=event_id,
            season=season,
            week=week,
            season_type=season_type,
            kickoff_utc=kickoff,
            home=home_team,
            away=away_team,
            venue=venue,
            neutral_site=bool(competition.get("neutralSite")),
            conference_game=bool(competition.get("conferenceCompetition")),
            status=status,
            home_score=scores[0],
            away_score=scores[1],
            winner_team_id=_winner_team_id(home, away, status),
            is_fbs_vs_fbs=True,
            odds=None,
            weather=None,
            team_stats=team_stats,
            field_provenance=provenance,
            source="espn",
            fetched_at=stamp,
        )

    def parse_odds(
        self,
        items: list[dict[str, Any]] | dict[str, Any],
        *,
        home_team_id: str,
        away_team_id: str,
        kickoff: datetime,
        fetched_at: datetime | None = None,
        preferred_providers: list[str] | None = None,
    ) -> OddsInfo | None:
        if isinstance(items, dict):
            items = items.get("items", [])
        if not items:
            return None
        preferred = [name.lower() for name in preferred_providers or []]
        ordered = sorted(
            items,
            key=lambda item: _provider_priority(item, preferred),
        )
        for item in ordered:
            parsed = self._odds_item(
                item,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                kickoff=kickoff,
            )
            if parsed is not None:
                return parsed
        return None

    def _odds_item(
        self,
        item: dict[str, Any],
        *,
        home_team_id: str,
        away_team_id: str,
        kickoff: datetime,
    ) -> OddsInfo | None:
        home = item.get("homeTeamOdds") or {}
        away = item.get("awayTeamOdds") or {}
        favorite_is_home = _favorite_is_home(item, home, away)
        favorite_team_id = home_team_id if favorite_is_home else away_team_id
        favorite_side = home if favorite_is_home else away
        spread_open = _spread(favorite_side.get("open"))
        spread = _spread(favorite_side.get("current")) or _spread(favorite_side.get("close"))
        if spread is None:
            spread = _details_spread(item.get("details"))
        if spread_open is None and spread is None:
            return None
        open_total = _total(item.get("open")) or _optional_float(item.get("overUnder"))
        known_at = derive_known_at("spread_open", kickoff)
        market_prob, prob_source = _moneyline_probability(item, favorite_is_home)
        return OddsInfo(
            provider=(item.get("provider") or {}).get("name"),
            favorite_team_id=favorite_team_id,
            spread=spread,
            spread_open=spread_open,
            over_under=open_total,
            market_prob=market_prob,
            favorite_source=FavoriteSource.ESPN_OPEN,
            line_provider=(item.get("provider") or {}).get("name"),
            market_prob_source=prob_source,
            known_at=known_at,
        )

    def parse_rankings(self, payload: dict[str, Any]) -> Rankings:
        rankings = payload.get("rankings") or []
        chosen = next((item for item in rankings if item.get("id") == "1"), None)
        if chosen is None and rankings:
            chosen = rankings[0]
        requested = payload.get("requestedSeason") or {}
        season = int(requested.get("year") or 0)
        week = (requested.get("week") or {}).get("number")
        ranks: dict[str, int] = {}
        published_at: datetime | None = None
        if chosen is not None:
            for entry in chosen.get("ranks", []):
                rank = entry.get("current")
                team_id = str((entry.get("team") or {}).get("id") or "")
                if team_id and isinstance(rank, int) and 1 <= rank <= 25:
                    ranks[team_id] = rank
            published_at = _parse_datetime(chosen.get("lastUpdated") or chosen.get("date"))
        return Rankings(
            season=season,
            week=week,
            poll=(chosen or {}).get("shortName") or (chosen or {}).get("name") or "AP Poll",
            ranks=ranks,
            published_at=published_at,
        )

    def parse_groups(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[GroupInfo]:
        raw_groups: list[dict[str, Any]]
        if isinstance(payload, list):
            raw_groups = payload
        else:
            raw_groups = payload.get("items") or payload.get("groups") or []
        groups: list[GroupInfo] = []
        for group in raw_groups:
            parent = group.get("parent") or {}
            team_ids: list[str] = []
            for team in group.get("teams", []):
                team_id = team.get("id") if isinstance(team, dict) else team
                if team_id is not None:
                    team_ids.append(str(team_id))
            groups.append(
                GroupInfo(
                    group_id=str(group.get("id") or ""),
                    name=group.get("name") or group.get("shortName") or "",
                    parent_id=str(parent.get("id")) if parent.get("id") else None,
                    team_ids=team_ids,
                )
            )
        return groups


# ---------------------------------------------------------------------------
# Pure helpers (also used by fixture parity tests)
# ---------------------------------------------------------------------------


def american_to_probability(american: float) -> float:
    """Convert American odds to an implied probability (with vig)."""

    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _moneyline_probability(
    item: dict[str, Any],
    favorite_is_home: bool,
) -> tuple[float | None, MarketProbSource]:
    home = item.get("homeTeamOdds") or {}
    away = item.get("awayTeamOdds") or {}
    home_line = _american(home.get("current") or home.get("open")) or _american(item.get("home"))
    away_line = _american(away.get("current") or away.get("open")) or _american(item.get("away"))
    if home_line is None or away_line is None:
        return None, MarketProbSource.UNAVAILABLE
    home_prob = american_to_probability(home_line)
    away_prob = american_to_probability(away_line)
    total = home_prob + away_prob
    if total <= 0:
        return None, MarketProbSource.UNAVAILABLE
    no_vig_home = home_prob / total
    return (no_vig_home if favorite_is_home else 1.0 - no_vig_home), MarketProbSource.MONEYLINE


def _provider_priority(item: dict[str, Any], preferred: list[str]) -> tuple[int, int]:
    name = str((item.get("provider") or {}).get("name") or "").lower()
    for index, candidate in enumerate(preferred):
        if candidate and candidate in name:
            return (index, 0)
    return (len(preferred), 1)


def _favorite_is_home(
    item: dict[str, Any],
    home: dict[str, Any],
    away: dict[str, Any],
) -> bool:
    if home.get("favoriteAtOpen") is not None:
        return bool(home.get("favoriteAtOpen"))
    if home.get("favorite") is not None:
        return bool(home.get("favorite"))
    details = str(item.get("details") or "")
    home_abbr = str((home.get("team") or {}).get("abbreviation") or "")
    return bool(home_abbr and details.upper().startswith(home_abbr.upper()))


def _spread(block: Any) -> float | None:
    if not isinstance(block, dict):
        return None
    for key in ("pointSpread", "spread"):
        value = block.get(key)
        if isinstance(value, dict):
            for field_name in ("alternateDisplayValue", "american"):
                parsed = _optional_float(value.get(field_name))
                if parsed is not None:
                    return parsed
            parsed = _optional_float(value.get("value"))
            if parsed is not None:
                return parsed
    return None


def _details_spread(details: Any) -> float | None:
    """Parse ``"ND -25.5"`` / ``"SYR +3"`` into the favourite-perspective spread."""

    if not isinstance(details, str):
        return None
    parts = details.split()
    if len(parts) < 2:
        return None
    value = _optional_float(parts[-1])
    if value is None:
        return None
    return -abs(value)


def _total(block: Any) -> float | None:
    if not isinstance(block, dict):
        return None
    total = block.get("total")
    if isinstance(total, dict):
        for field_name in ("alternateDisplayValue", "american", "value"):
            parsed = _optional_float(total.get(field_name))
            if parsed is not None:
                return parsed
    return None


def _american(block: Any) -> float | None:
    if not isinstance(block, dict):
        return None
    line = block.get("moneyLine")
    if isinstance(line, dict):
        return _optional_float(line.get("american"))
    if line is not None:
        return _optional_float(line)
    return None


def _team_info(competitor: dict[str, Any]) -> TeamInfo | None:
    team = competitor.get("team") or {}
    team_id = str(competitor.get("id") or team.get("id") or "")
    if not team_id:
        return None
    school = team.get("location") or team.get("shortDisplayName") or team.get("displayName")
    if not school:
        return None
    rank = None
    curated = (competitor.get("curatedRank") or {}).get("current")
    if isinstance(curated, int) and 1 <= curated <= 25:
        rank = curated
    record = None
    for entry in competitor.get("records") or []:
        if entry.get("type") in {"total", None} and entry.get("summary"):
            record = entry["summary"]
            break
    return TeamInfo(
        team_id=team_id,
        school=str(school),
        nickname=team.get("name"),
        abbreviation=team.get("abbreviation"),
        conference=str(team["conferenceId"]) if team.get("conferenceId") else None,
        is_fbs=True,
        color=team.get("color"),
        alt_color=team.get("alternateColor"),
        logo_url=team.get("logo"),
        rank=rank,
        record=record,
    )


def _venue_info(raw: Any) -> VenueInfo | None:
    if not isinstance(raw, dict) or not raw:
        return None
    address = raw.get("address") or {}
    name = raw.get("fullName") or raw.get("name")
    if not name:
        return None
    return VenueInfo(
        venue_id=str(raw["id"]) if raw.get("id") is not None else None,
        name=str(name),
        city=address.get("city"),
        state=address.get("state"),
        country=address.get("country"),
        indoor=raw.get("indoor"),
        grass=raw.get("grass"),
        source="espn",
    )


def _status(raw: Any) -> GameStatus:
    if not isinstance(raw, dict):
        return GameStatus.SCHEDULED
    type_info = raw.get("type") or {}
    name = str(type_info.get("name") or "").upper()
    state = str(type_info.get("state") or "").lower()
    description = str(type_info.get("description") or "").lower()
    if "POSTPONED" in name or "postponed" in description:
        return GameStatus.POSTPONED
    if "CANCELED" in name or "CANCELLED" in name or "canceled" in description:
        return GameStatus.CANCELED
    if type_info.get("completed") or state == "post":
        return GameStatus.FINAL
    if state == "in":
        return GameStatus.IN_PROGRESS
    return GameStatus.SCHEDULED


def _scores(
    home: dict[str, Any],
    away: dict[str, Any],
    status: GameStatus,
) -> tuple[int | None, int | None]:
    if status not in {GameStatus.FINAL, GameStatus.IN_PROGRESS}:
        return None, None
    return _optional_int(home.get("score")), _optional_int(away.get("score"))


def _winner_team_id(
    home: dict[str, Any],
    away: dict[str, Any],
    status: GameStatus,
) -> str | None:
    if status is not GameStatus.FINAL:
        return None
    if home.get("winner"):
        return str(home.get("id") or (home.get("team") or {}).get("id") or "") or None
    if away.get("winner"):
        return str(away.get("id") or (away.get("team") or {}).get("id") or "") or None
    return None


def _team_stats(boxscore: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    stats: dict[str, dict[str, float | None]] = {}
    for team_block in boxscore.get("teams", []):
        team = team_block.get("team") or {}
        team_id = str(team.get("id") or "")
        if not team_id:
            continue
        values: dict[str, float | None] = {}
        for item in team_block.get("statistics", []):
            name = item.get("name")
            if not name:
                continue
            values[str(name)] = _optional_float(item.get("value"))
        stats[team_id] = values
    return stats


def _provenance(
    *,
    source: str,
    source_url: str,
    fetched_at: datetime,
    kickoff: datetime,
    fields: dict[str, str | None],
) -> dict[str, Provenance]:
    provenance: dict[str, Provenance] = {}
    for field_name, group in fields.items():
        if group is None:
            known_at = kickoff  # post-game: strictly excluded by admit()
        else:
            known_at = derive_known_at(field_name, kickoff)
        provenance[field_name] = Provenance(
            source=source,
            source_url=source_url,
            fetched_at=fetched_at,
            known_at=known_at,
        )
    return provenance


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _season_from_date(kickoff: datetime) -> int:
    return kickoff.year


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first(items: Any) -> dict[str, Any] | None:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return None


__all__ = ["EspnAdapter", "FBS_GROUP_ID", "GroupInfo", "Rankings", "american_to_probability"]
