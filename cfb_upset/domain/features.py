"""Leakage-safe pre-game features (P3.1/P3.2).

Every value in this module is computed from games that *finished* strictly
before the current kickoff. The builder walks the corpus in kickoff order and
only releases a result into the rolling state once ``kickoff + game_duration``
is earlier than the next kickoff. That single rule is what makes a
same-slate game, a later game, or a post-game box score incapable of changing
an earlier feature.

Feature rows carry an explicit, conservative ``known_at``. It is the later of
the schedule lead time and the most recent result that contributed to the
value, so ``known_at < kickoff`` is always provable by
``cfb_upset.domain.leakage.admit``.

The module is pure: it takes ``FeatureGame`` values and returns rows. Database
loading lives in ``pipelines/build_features.py``.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from cfb_upset.contracts import FavoriteSource, MarketProbSource, OddsInfo, VenueInfo
from cfb_upset.domain.leakage import LeakageError, admit

DEFAULT_FEATURE_VERSION = "features_v1"
SCHEDULE_LEAD = timedelta(days=7)
GAME_DURATION = timedelta(hours=4)


@dataclass(frozen=True)
class FeatureConfig:
    """Tunables for the deterministic feature build (see ``configs/features.yaml``)."""

    feature_version: str = DEFAULT_FEATURE_VERSION
    game_duration: timedelta = GAME_DURATION
    schedule_lead: timedelta = SCHEDULE_LEAD
    form_window: int = 3
    home_field_elo: float = 65.0
    elo_k: float = 20.0
    season_regression: float = 0.75
    spread_sigma: float = 13.5
    short_week_days: float = 7.0
    post_bye_days: float = 14.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> FeatureConfig:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        scalars = {
            "feature_version": payload.get("feature_version", DEFAULT_FEATURE_VERSION),
            "form_window": int(payload.get("form_window", 3)),
            "home_field_elo": float(payload.get("home_field_elo", 65.0)),
            "elo_k": float(payload.get("elo_k", 20.0)),
            "season_regression": float(payload.get("season_regression", 0.75)),
            "spread_sigma": float(payload.get("spread_sigma", 13.5)),
            "short_week_days": float(payload.get("short_week_days", 7.0)),
            "post_bye_days": float(payload.get("post_bye_days", 14.0)),
        }
        duration = payload.get("game_duration_hours")
        lead = payload.get("schedule_lead_days")
        return cls(
            **scalars,
            game_duration=timedelta(hours=float(duration)) if duration else GAME_DURATION,
            schedule_lead=timedelta(days=float(lead)) if lead else SCHEDULE_LEAD,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "game_duration_hours": self.game_duration.total_seconds() / 3600.0,
            "schedule_lead_days": self.schedule_lead.total_seconds() / 86400.0,
            "form_window": self.form_window,
            "home_field_elo": self.home_field_elo,
            "elo_k": self.elo_k,
            "season_regression": self.season_regression,
            "spread_sigma": self.spread_sigma,
            "short_week_days": self.short_week_days,
            "post_bye_days": self.post_bye_days,
        }


@dataclass(frozen=True)
class FeatureGame:
    """One game projected for feature computation.

    ``home_rank``/``away_rank`` are the AP poll ranks available *before* this
    game (P2 applies the weekly poll). ``odds`` is the ESPN open market;
    ``cfbd_spread_open`` is an optional signed home-perspective CFBD open
    (negative = home favoured) used first when present.
    """

    game_id: str
    season: int
    week: int | None
    season_type: int
    kickoff: datetime
    home_team_id: str
    away_team_id: str
    neutral_site: bool
    conference_game: bool
    venue_id: str | None
    status: str
    home_score: int | None
    away_score: int | None
    home_rank: int | None = None
    away_rank: int | None = None
    rank_known_at: datetime | None = None
    odds: OddsInfo | None = None
    cfbd_spread_open: float | None = None
    cfbd_line_provider: str | None = None

    @property
    def final(self) -> bool:
        return (
            self.status.upper() == "FINAL"
            and self.home_score is not None
            and self.away_score is not None
        )


@dataclass(frozen=True)
class FeatureRow:
    game_id: str
    feature_name: str
    value: float | None
    known_at: datetime


@dataclass(frozen=True)
class DerivedField:
    """A non-numeric pre-game value stored in ``game_fields``."""

    game_id: str
    field_name: str
    value: Any
    known_at: datetime


@dataclass(frozen=True)
class MarketContext:
    favorite_team_id: str | None
    favorite_source: FavoriteSource
    line_provider: str | None
    market_prob: float | None
    market_prob_source: MarketProbSource
    spread_open: float | None
    known_at: datetime


@dataclass(frozen=True)
class GameLabel:
    """Evaluation-only label; never written to ``game_features``."""

    game_id: str
    season: int
    week: int | None
    kickoff: datetime
    home_team_id: str
    away_team_id: str
    favorite_team_id: str | None
    favorite_source: str
    market_prob: float | None
    upset: bool | None
    margin: int | None


@dataclass(frozen=True)
class FeatureAudit:
    rows: int
    leaked: int
    unknown_fields: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.leaked == 0 and not self.unknown_fields


@dataclass
class FeatureResult:
    config: FeatureConfig
    rows: list[FeatureRow]
    fields: list[DerivedField]
    labels: list[GameLabel]
    wide_rows: list[dict[str, Any]]
    audit: FeatureAudit
    games: int = 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_features(
    games: Sequence[FeatureGame],
    *,
    venues: Mapping[str, VenueInfo] | None = None,
    config: FeatureConfig | None = None,
) -> FeatureResult:
    """Compute every P3 feature for ``games`` without looking past kickoff."""

    cfg = config or FeatureConfig()
    venues = venues or {}
    ordered = sorted(games, key=lambda game: (game.kickoff, game.game_id))
    _require_aware_games(ordered)
    _require_unique_ids(ordered)

    home_venues = _modal_home_venues(ordered)
    week_ranks = _week_ranks(ordered)
    next_opponents = _next_opponents(ordered)

    history: dict[tuple[str, int], list[_Result]] = defaultdict(list)
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    elo_season: dict[str, int] = {}
    rank_history: dict[str, list[tuple[int, int | None, int | None, datetime]]] = defaultdict(list)

    rows: list[FeatureRow] = []
    fields: list[DerivedField] = []
    labels: list[GameLabel] = []
    wide_rows: list[dict[str, Any]] = []

    add_index = 0
    latest_result_known: datetime | None = None

    for game in ordered:
        schedule_known = game.kickoff - cfg.schedule_lead
        while add_index < len(ordered):
            candidate = ordered[add_index]
            if not (candidate.kickoff + cfg.game_duration < game.kickoff):
                break
            if candidate.final:
                _release_result(
                    candidate,
                    history=history,
                    elo=elo,
                    elo_season=elo_season,
                    config=cfg,
                )
                known = candidate.kickoff + cfg.game_duration
                if latest_result_known is None or known > latest_result_known:
                    latest_result_known = known
            add_index += 1

        state_known = (
            max(schedule_known, latest_result_known) if latest_result_known else schedule_known
        )
        rank_known = _rank_known_at(game, fallback=schedule_known)
        combined_known = max(state_known, rank_known)

        home_state = _team_state(game.home_team_id, game.season, history, kickoff=game.kickoff)
        away_state = _team_state(game.away_team_id, game.season, history, kickoff=game.kickoff)
        home_strength = _pre_game_elo(
            game.home_team_id,
            game.season,
            elo=elo,
            elo_season=elo_season,
            config=cfg,
        ) + (0.0 if game.neutral_site else cfg.home_field_elo)
        away_strength = _pre_game_elo(
            game.away_team_id,
            game.season,
            elo=elo,
            elo_season=elo_season,
            config=cfg,
        )

        home_venue = venues.get(home_venues.get(game.home_team_id) or "")
        game_venue = venues.get(game.venue_id or "")
        home_travel = _travel_km(home_venue, game_venue)
        away_travel = _travel_km(venues.get(home_venues.get(game.away_team_id) or ""), game_venue)
        home_tz = _tz_delta_hours(home_venue, game_venue, game.kickoff)
        away_tz = _tz_delta_hours(
            venues.get(home_venues.get(game.away_team_id) or ""), game_venue, game.kickoff
        )

        home_rank = game.home_rank
        away_rank = game.away_rank
        home_prev = _previous_rank(rank_history.get(game.home_team_id), game)
        away_prev = _previous_rank(rank_history.get(game.away_team_id), game)
        home_next = next_opponents.get((game.game_id, game.home_team_id))
        away_next = next_opponents.get((game.game_id, game.away_team_id))
        home_next_rank = week_ranks.get((game.season, game.week), {}).get(home_next or "")
        away_next_rank = week_ranks.get((game.season, game.week), {}).get(away_next or "")

        market = resolve_market(
            game,
            strength_diff=home_strength - away_strength,
            state_known=state_known,
            config=cfg,
        )

        values: dict[str, tuple[float | None, datetime]] = {}
        _add_pair(values, "wins", home_state["wins"], away_state["wins"], state_known)
        _add_pair(values, "losses", home_state["losses"], away_state["losses"], state_known)
        _add_pair(values, "win_pct", home_state["win_pct"], away_state["win_pct"], state_known)
        _add_pair(
            values, "point_diff", home_state["point_diff"], away_state["point_diff"], state_known
        )
        _add_pair(
            values,
            "scoring_off",
            home_state["scoring_off"],
            away_state["scoring_off"],
            state_known,
        )
        _add_pair(
            values,
            "defensive_allow",
            home_state["defensive_allow"],
            away_state["defensive_allow"],
            state_known,
        )
        _add_pair(values, "sos", home_state["sos"], away_state["sos"], state_known)
        _add_pair(
            values,
            "last3_win_pct",
            home_state["last3_win_pct"],
            away_state["last3_win_pct"],
            state_known,
        )
        _add_pair(
            values,
            "last3_point_diff",
            home_state["last3_point_diff"],
            away_state["last3_point_diff"],
            state_known,
        )
        _add_pair(values, "pace_total", home_state["pace"], away_state["pace"], state_known)
        _add_pair(
            values, "rest_days", home_state["rest_days"], away_state["rest_days"], state_known
        )
        _add_pair(
            values,
            "short_week",
            _flag(home_state["rest_days"], cfg.short_week_days, below=True),
            _flag(away_state["rest_days"], cfg.short_week_days, below=True),
            state_known,
        )
        _add_pair(
            values,
            "post_bye",
            _flag(home_state["rest_days"], cfg.post_bye_days, below=False),
            _flag(away_state["rest_days"], cfg.post_bye_days, below=False),
            state_known,
        )
        _add_pair(values, "travel_km", home_travel, away_travel, state_known)
        _add_pair(values, "tz_delta", home_tz, away_tz, state_known)
        _add_pair(
            values,
            "season_game_number",
            float(home_state["games"] + 1),
            float(away_state["games"] + 1),
            state_known,
        )
        values["altitude_m"] = (game_venue.altitude_m if game_venue else None, schedule_known)
        values["neutral_site"] = (float(game.neutral_site), schedule_known)
        values["conference_game"] = (float(game.conference_game), schedule_known)
        values["home_away_home"] = (1.0, schedule_known)
        values["home_away_away"] = (0.0, schedule_known)
        values["rank_home"] = (None if home_rank is None else float(home_rank), rank_known)
        values["rank_away"] = (None if away_rank is None else float(away_rank), rank_known)
        values["is_ranked_home"] = (
            None if game.season_type != 2 else float(home_rank is not None),
            rank_known,
        )
        values["is_ranked_away"] = (
            None if game.season_type != 2 else float(away_rank is not None),
            rank_known,
        )
        values["rank_delta_home"] = (
            None if home_prev is None or home_rank is None else float(home_prev - home_rank),
            combined_known,
        )
        values["rank_delta_away"] = (
            None if away_prev is None or away_rank is None else float(away_prev - away_rank),
            combined_known,
        )
        values["look_ahead_home"] = (
            None if home_next is None else float(home_next_rank is not None),
            combined_known,
        )
        values["look_ahead_away"] = (
            None if away_next is None else float(away_next_rank is not None),
            combined_known,
        )
        values["look_ahead_rank_home"] = (
            None if home_next_rank is None else float(home_next_rank),
            rank_known,
        )
        values["look_ahead_rank_away"] = (
            None if away_next_rank is None else float(away_next_rank),
            rank_known,
        )
        values["elo_home"] = (home_strength, state_known)
        values["elo_away"] = (away_strength, state_known)
        values["elo_diff"] = (home_strength - away_strength, state_known)
        values["strength_home"] = (home_strength, state_known)
        values["strength_away"] = (away_strength, state_known)
        values["strength_diff"] = (home_strength - away_strength, state_known)
        values["is_favorite_home"] = (
            (
                None
                if market.favorite_team_id is None
                else float(market.favorite_team_id == game.home_team_id)
            ),
            market.known_at,
        )
        values["is_favorite_away"] = (
            (
                None
                if market.favorite_team_id is None
                else float(market.favorite_team_id == game.away_team_id)
            ),
            market.known_at,
        )
        values["market_prob_home"] = (
            (
                None
                if market.market_prob is None
                else (
                    market.market_prob
                    if market.favorite_team_id == game.home_team_id
                    else 1.0 - market.market_prob
                )
            ),
            market.known_at,
        )
        values["spread_open_abs"] = (market.spread_open, market.known_at)

        for feature_name, (value, known_at) in values.items():
            rows.append(
                FeatureRow(
                    game_id=game.game_id,
                    feature_name=feature_name,
                    value=_clean_float(value),
                    known_at=known_at,
                )
            )
        fields.extend(_market_fields(game.game_id, market))

        if game.final:
            winner = (
                game.home_team_id
                if game.home_score > game.away_score
                else game.away_team_id if game.away_score > game.home_score else None
            )
            upset = (
                None
                if winner is None or market.favorite_team_id is None
                else winner != market.favorite_team_id
            )
            labels.append(
                GameLabel(
                    game_id=game.game_id,
                    season=game.season,
                    week=game.week,
                    kickoff=game.kickoff,
                    home_team_id=game.home_team_id,
                    away_team_id=game.away_team_id,
                    favorite_team_id=market.favorite_team_id,
                    favorite_source=market.favorite_source.value,
                    market_prob=market.market_prob,
                    upset=upset,
                    margin=game.home_score - game.away_score,
                )
            )

        wide: dict[str, Any] = {
            "game_id": game.game_id,
            "season": game.season,
            "week": game.week,
            "season_type": game.season_type,
            "kickoff_utc": game.kickoff,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
        }
        wide.update({name: _clean_float(value) for name, (value, _known) in values.items()})
        wide_rows.append(wide)

        _remember_rank(
            rank_history,
            game.home_team_id,
            game.season,
            game.week,
            home_rank,
            rank_known,
        )
        _remember_rank(
            rank_history,
            game.away_team_id,
            game.season,
            game.week,
            away_rank,
            rank_known,
        )

    audit = audit_features(rows, ordered)
    return FeatureResult(
        config=cfg,
        rows=rows,
        fields=fields,
        labels=labels,
        wide_rows=wide_rows,
        audit=audit,
        games=len(ordered),
    )


# ---------------------------------------------------------------------------
# Market / favourite policy (P3.2)
# ---------------------------------------------------------------------------


def resolve_market(
    game: FeatureGame,
    *,
    strength_diff: float,
    state_known: datetime,
    config: FeatureConfig | None = None,
) -> MarketContext:
    """CFBD open -> ESPN open -> rolling strength proxy (D4).

    ``market_prob`` is admitted only when its ``known_at`` is strictly before
    kickoff. A strength-proxy favourite deliberately records
    ``market_prob_source=unavailable`` rather than a made-up probability.
    """

    cfg = config or FeatureConfig()
    if game.cfbd_spread_open is not None and game.cfbd_spread_open != 0:
        favorite = game.home_team_id if game.cfbd_spread_open < 0 else game.away_team_id
        spread = abs(float(game.cfbd_spread_open))
        known_at = game.kickoff - SCHEDULE_LEAD
        return _with_probability(
            game,
            favorite=favorite,
            source=FavoriteSource.CFBD_OPEN,
            line_provider=game.cfbd_line_provider or "cfbd",
            spread=spread,
            known_at=known_at,
            market_prob=None,
            market_prob_source=MarketProbSource.UNAVAILABLE,
            config=cfg,
        )

    odds = game.odds
    if odds is not None and odds.spread_open is not None and odds.favorite_team_id is not None:
        known_at = odds.known_at
        prob = odds.market_prob
        prob_source = (
            odds.market_prob_source if prob is not None else MarketProbSource.SPREAD_MAPPED
        )
        return _with_probability(
            game,
            favorite=odds.favorite_team_id,
            source=(
                FavoriteSource.CFBD_OPEN
                if odds.favorite_source == FavoriteSource.CFBD_OPEN
                else FavoriteSource.ESPN_OPEN
            ),
            line_provider=odds.line_provider or odds.provider,
            spread=abs(float(odds.spread_open)),
            known_at=known_at,
            market_prob=prob,
            market_prob_source=prob_source,
            config=cfg,
        )

    favorite = game.home_team_id if strength_diff >= 0 else game.away_team_id
    return MarketContext(
        favorite_team_id=favorite,
        favorite_source=FavoriteSource.STRENGTH_PROXY,
        line_provider=None,
        market_prob=None,
        market_prob_source=MarketProbSource.UNAVAILABLE,
        spread_open=None,
        known_at=state_known,
    )


def spread_probability(spread: float, *, sigma: float = 13.5) -> float:
    """Map an absolute point spread to a no-vig favourite win probability."""

    if spread < 0:
        raise ValueError("spread must be the absolute favourite spread")
    # Normal CDF with a CFB-calibrated margin standard deviation.
    return 0.5 * (1.0 + math.erf(spread / (sigma * math.sqrt(2.0))))


def _with_probability(
    game: FeatureGame,
    *,
    favorite: str,
    source: FavoriteSource,
    line_provider: str | None,
    spread: float,
    known_at: datetime,
    market_prob: float | None,
    market_prob_source: MarketProbSource,
    config: FeatureConfig,
) -> MarketContext:
    admitted = market_prob
    admitted_source = market_prob_source
    if admitted is not None:
        try:
            admit("market_prob", known_at, game.kickoff, source="feature_builder")
        except LeakageError:
            admitted = None
            admitted_source = MarketProbSource.UNAVAILABLE
    elif market_prob_source == MarketProbSource.SPREAD_MAPPED:
        # A spread-mapped probability is derived from the opening line, so it
        # inherits the line's pre-kickoff timestamp.
        try:
            admit("market_prob", known_at, game.kickoff, source="feature_builder")
        except LeakageError:
            admitted_source = MarketProbSource.UNAVAILABLE
        else:
            admitted = spread_probability(spread, sigma=config.spread_sigma)
    return MarketContext(
        favorite_team_id=favorite,
        favorite_source=source,
        line_provider=line_provider,
        market_prob=admitted,
        market_prob_source=admitted_source,
        spread_open=spread,
        known_at=known_at,
    )


def _market_fields(game_id: str, market: MarketContext) -> list[DerivedField]:
    fields = [
        DerivedField(game_id, "favorite_source", market.favorite_source.value, market.known_at),
        DerivedField(
            game_id, "market_prob_source", market.market_prob_source.value, market.known_at
        ),
    ]
    if market.favorite_team_id is not None:
        fields.append(
            DerivedField(game_id, "favorite_team_id", market.favorite_team_id, market.known_at)
        )
    if market.line_provider is not None:
        fields.append(DerivedField(game_id, "line_provider", market.line_provider, market.known_at))
    if market.market_prob is not None:
        fields.append(DerivedField(game_id, "market_prob", market.market_prob, market.known_at))
    if market.spread_open is not None:
        fields.append(DerivedField(game_id, "spread_open", market.spread_open, market.known_at))
    return fields


# ---------------------------------------------------------------------------
# Audit + rolling helpers
# ---------------------------------------------------------------------------


def audit_features(rows: Iterable[FeatureRow], games: Sequence[FeatureGame]) -> FeatureAudit:
    """Prove every row is admissible; return counts instead of raising."""

    materialized = list(rows)
    kickoffs = {game.game_id: game.kickoff for game in games}
    leaked = 0
    unknown: set[str] = set()
    violations: list[str] = []
    for row in materialized:
        kickoff = kickoffs[row.game_id]
        try:
            admit(row.feature_name, row.known_at, kickoff, source="feature_builder")
        except LeakageError as exc:
            message = str(exc)
            violations.append(f"{row.game_id}/{row.feature_name}: {message}")
            if "not in the leakage policy" in message:
                unknown.add(row.feature_name)
            else:
                leaked += 1
    return FeatureAudit(
        rows=len(materialized),
        leaked=leaked,
        unknown_fields=sorted(unknown),
        violations=violations[:50],
    )


@dataclass(frozen=True)
class _Result:
    kickoff: datetime
    season: int
    team_score: int
    opponent_score: int
    opponent_id: str

    @property
    def won(self) -> bool:
        return self.team_score > self.opponent_score


def _release_result(
    game: FeatureGame,
    *,
    history: dict[tuple[str, int], list[_Result]],
    elo: dict[str, float],
    elo_season: dict[str, int],
    config: FeatureConfig,
) -> None:
    assert game.home_score is not None and game.away_score is not None
    history[(game.home_team_id, game.season)].append(
        _Result(
            game.kickoff,
            game.season,
            game.home_score,
            game.away_score,
            game.away_team_id,
        )
    )
    history[(game.away_team_id, game.season)].append(
        _Result(
            game.kickoff,
            game.season,
            game.away_score,
            game.home_score,
            game.home_team_id,
        )
    )
    home_elo = _pre_game_elo(
        game.home_team_id, game.season, elo=elo, elo_season=elo_season, config=config
    )
    away_elo = _pre_game_elo(
        game.away_team_id, game.season, elo=elo, elo_season=elo_season, config=config
    )
    home_advantage = 0.0 if game.neutral_site else config.home_field_elo
    expected_home = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - home_advantage) / 400.0))
    actual_home = 1.0 if game.home_score > game.away_score else 0.0
    if game.home_score == game.away_score:
        actual_home = 0.5
    delta = config.elo_k * (actual_home - expected_home)
    elo[game.home_team_id] = home_elo + delta
    elo[game.away_team_id] = away_elo - delta


def _pre_game_elo(
    team_id: str,
    season: int,
    *,
    elo: dict[str, float],
    elo_season: dict[str, int],
    config: FeatureConfig,
) -> float:
    rating = elo[team_id]
    if elo_season.get(team_id) != season:
        rating = 1500.0 + config.season_regression * (rating - 1500.0)
        elo[team_id] = rating
        elo_season[team_id] = season
    return rating


def _team_state(
    team_id: str,
    season: int,
    history: Mapping[tuple[str, int], Sequence[_Result]],
    *,
    kickoff: datetime,
) -> dict[str, Any]:
    results = list(history.get((team_id, season), ()))
    games = len(results)
    wins = sum(1 for result in results if result.won)
    losses = games - wins
    margins = [result.team_score - result.opponent_score for result in results]
    totals = [result.team_score + result.opponent_score for result in results]
    recent = results[-3:]
    rest_days = (kickoff - results[-1].kickoff).total_seconds() / 86400.0 if results else None
    return {
        "games": games,
        "wins": float(wins),
        "losses": float(losses),
        "win_pct": wins / games if games else None,
        "point_diff": _mean(margins),
        "scoring_off": _mean([result.team_score for result in results]),
        "defensive_allow": _mean([result.opponent_score for result in results]),
        "sos": _sos(results, history),
        "last3_win_pct": (
            sum(1 for result in recent if result.won) / len(recent) if recent else None
        ),
        "last3_point_diff": _mean([result.team_score - result.opponent_score for result in recent]),
        "pace": _mean(totals),
        "rest_days": rest_days,
        "last_kickoff": results[-1].kickoff if results else None,
    }


def _sos(
    results: Sequence[_Result],
    history: Mapping[tuple[str, int], Sequence[_Result]],
) -> float | None:
    values: list[float] = []
    for result in results:
        opponent_results = history.get((result.opponent_id, result.season), ())
        if not opponent_results:
            continue
        wins = sum(1 for game in opponent_results if game.won)
        values.append(wins / len(opponent_results))
    return _mean(values)


def _mean(values: Sequence[float] | Sequence[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _flag(value: float | None, threshold: float, *, below: bool) -> float | None:
    if value is None:
        return None
    return float(value < threshold) if below else float(value >= threshold)


def _clean_float(value: float | None) -> float | None:
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return float(value)


def _add_pair(
    values: dict[str, tuple[float | None, datetime]],
    name: str,
    home: float | None,
    away: float | None,
    known_at: datetime,
) -> None:
    values[f"{name}_home"] = (home, known_at)
    values[f"{name}_away"] = (away, known_at)


def _rank_known_at(game: FeatureGame, *, fallback: datetime) -> datetime:
    if game.rank_known_at is not None:
        if game.rank_known_at >= game.kickoff:
            raise LeakageError(
                f"rank known_at {game.rank_known_at.isoformat()} >= kickoff " f"for {game.game_id}"
            )
        return game.rank_known_at
    return fallback


def _previous_rank(
    history: Sequence[tuple[int, int | None, int | None, datetime]] | None,
    game: FeatureGame,
) -> int | None:
    """Return the most recent rank from a strictly earlier week."""

    if not history:
        return None
    for season, week, rank, _known in reversed(history):
        if season != game.season:
            continue
        if week is None or game.week is None or week >= game.week:
            continue
        return rank
    return None


def _remember_rank(
    history: dict[str, list[tuple[int, int | None, int | None, datetime]]],
    team_id: str,
    season: int,
    week: int | None,
    rank: int | None,
    known_at: datetime,
) -> None:
    entries = history[team_id]
    if entries and entries[-1] == (season, week, rank, known_at):
        return
    entries.append((season, week, rank, known_at))


def _modal_home_venues(games: Sequence[FeatureGame]) -> dict[str, str]:
    """Infer each team's home venue from its non-neutral home games."""

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for game in games:
        if game.neutral_site or not game.venue_id:
            continue
        counts[game.home_team_id][game.venue_id] += 1
    resolved: dict[str, str] = {}
    for team_id, counter in counts.items():
        resolved[team_id] = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return resolved


def _week_ranks(games: Sequence[FeatureGame]) -> dict[tuple[int, int | None], dict[str, int]]:
    ranks: dict[tuple[int, int | None], dict[str, int]] = defaultdict(dict)
    for game in games:
        bucket = ranks[(game.season, game.week)]
        if game.home_rank is not None:
            bucket[game.home_team_id] = game.home_rank
        if game.away_rank is not None:
            bucket[game.away_team_id] = game.away_rank
    return dict(ranks)


def _next_opponents(games: Sequence[FeatureGame]) -> dict[tuple[str, str], str]:
    """Map ``(game_id, team_id)`` to that team's next opponent."""

    schedules: dict[str, list[FeatureGame]] = defaultdict(list)
    for game in games:
        schedules[game.home_team_id].append(game)
        schedules[game.away_team_id].append(game)
    next_opponent: dict[tuple[str, str], str] = {}
    for team_id, team_games in schedules.items():
        team_games.sort(key=lambda game: (game.kickoff, game.game_id))
        for current, following in zip(team_games, team_games[1:], strict=False):
            opponent = (
                following.away_team_id
                if following.home_team_id == team_id
                else following.home_team_id
            )
            next_opponent[(current.game_id, team_id)] = opponent
    return next_opponent


def _travel_km(origin: VenueInfo | None, destination: VenueInfo | None) -> float | None:
    if origin is None or destination is None:
        return None
    if None in (origin.lat, origin.lon, destination.lat, destination.lon):
        return None
    return _haversine_km(origin.lat, origin.lon, destination.lat, destination.lon)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _tz_delta_hours(
    origin: VenueInfo | None, destination: VenueInfo | None, instant: datetime
) -> float | None:
    if origin is None or destination is None or not origin.tz or not destination.tz:
        return None
    try:
        origin_offset = instant.astimezone(ZoneInfo(origin.tz)).utcoffset()
        destination_offset = instant.astimezone(ZoneInfo(destination.tz)).utcoffset()
    except ZoneInfoNotFoundError:
        return None
    if origin_offset is None or destination_offset is None:
        return None
    return (destination_offset - origin_offset).total_seconds() / 3600.0


def _require_aware_games(games: Sequence[FeatureGame]) -> None:
    for game in games:
        if game.kickoff.tzinfo is None or game.kickoff.utcoffset() is None:
            raise ValueError(f"{game.game_id} has a naive kickoff")


def _require_unique_ids(games: Sequence[FeatureGame]) -> None:
    seen: set[str] = set()
    for game in games:
        if game.game_id in seen:
            raise ValueError(f"duplicate game_id {game.game_id}")
        seen.add(game.game_id)


__all__ = [
    "DEFAULT_FEATURE_VERSION",
    "DerivedField",
    "FeatureAudit",
    "FeatureConfig",
    "FeatureGame",
    "FeatureResult",
    "FeatureRow",
    "GameLabel",
    "MarketContext",
    "audit_features",
    "compute_features",
    "resolve_market",
    "spread_probability",
]
