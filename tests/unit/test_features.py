"""Leakage-safe feature tests: rolling order, rest/travel, Elo, and splits."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from cfb_upset.contracts import (
    FavoriteSource,
    MarketProbSource,
    OddsInfo,
    VenueInfo,
)
from cfb_upset.domain.features import (
    FeatureConfig,
    FeatureGame,
    compute_features,
    resolve_market,
    spread_probability,
)
from cfb_upset.domain.splits import (
    Split,
    assert_disjoint_order,
    assert_pre_cutoff,
    assert_split_boundaries,
    assignments,
    split_counts,
    split_for_season,
)

KICKOFF = datetime(2021, 9, 4, 16, 0, tzinfo=UTC)


def game(
    game_id: str,
    home: str,
    away: str,
    *,
    kickoff: datetime = KICKOFF,
    season: int = 2021,
    week: int | None = 1,
    home_score: int | None = 24,
    away_score: int | None = 17,
    home_rank: int | None = None,
    away_rank: int | None = None,
    rank_known_at: datetime | None = None,
    venue_id: str | None = None,
    neutral: bool = False,
    conference: bool = True,
    odds: OddsInfo | None = None,
    cfbd_spread_open: float | None = None,
    cfbd_line_provider: str | None = None,
) -> FeatureGame:
    return FeatureGame(
        game_id=game_id,
        season=season,
        week=week,
        season_type=2,
        kickoff=kickoff,
        home_team_id=home,
        away_team_id=away,
        neutral_site=neutral,
        conference_game=conference,
        venue_id=venue_id,
        status="final",
        home_score=home_score,
        away_score=away_score,
        home_rank=home_rank,
        away_rank=away_rank,
        rank_known_at=rank_known_at,
        odds=odds,
        cfbd_spread_open=cfbd_spread_open,
        cfbd_line_provider=cfbd_line_provider,
    )


def values(result, game_id: str) -> dict[str, float | None]:
    return {row.feature_name: row.value for row in result.rows if row.game_id == game_id}


def known(result, game_id: str) -> dict[str, datetime]:
    return {row.feature_name: row.known_at for row in result.rows if row.game_id == game_id}


def test_rolling_window_excludes_current_and_same_kickoff_games() -> None:
    config = FeatureConfig(game_duration=timedelta(hours=2))
    games = [
        game("g1", "A", "B", kickoff=KICKOFF, home_score=28, away_score=7),
        game("g2", "C", "D", kickoff=KICKOFF, home_score=21, away_score=14),
        game("g3", "A", "C", kickoff=KICKOFF + timedelta(hours=1)),
        game("g4", "A", "D", kickoff=KICKOFF + timedelta(hours=2, seconds=1)),
    ]
    result = compute_features(games, config=config)

    assert values(result, "g2")["wins_home"] == 0.0
    assert values(result, "g3")["wins_home"] == 0.0
    assert values(result, "g4")["wins_home"] == 1.0
    assert values(result, "g4")["point_diff_home"] == 21.0
    assert result.audit.ok


def test_rest_travel_timezone_and_altitude_math() -> None:
    home_venue = VenueInfo(
        venue_id="H",
        name="Home",
        lat=40.0,
        lon=-80.0,
        tz="America/New_York",
        altitude_m=50.0,
    )
    away_venue = VenueInfo(
        venue_id="D",
        name="Destination",
        lat=35.0,
        lon=-90.0,
        tz="America/Chicago",
        altitude_m=200.0,
    )
    games = [
        game("g1", "A", "B", venue_id="H"),
        game(
            "g2",
            "C",
            "A",
            kickoff=KICKOFF + timedelta(days=7),
            venue_id="D",
        ),
    ]
    result = compute_features(games, venues={"H": home_venue, "D": away_venue})

    row = values(result, "g2")
    assert row["rest_days_away"] == pytest.approx(7.0)
    assert row["travel_km_away"] == pytest.approx(1041.7, abs=1.0)  # ~40,-80 -> ~35,-90
    assert row["tz_delta_away"] == pytest.approx(-1.0)
    assert row["altitude_m"] == pytest.approx(200.0)
    assert row["neutral_site"] == 0.0
    assert row["conference_game"] == 1.0
    assert row["home_away_away"] == 0.0
    assert known(result, "g2")["travel_km_away"] < games[1].kickoff


def test_short_week_and_post_bye_flags() -> None:
    games = [
        game("g1", "A", "B"),
        game("g2", "A", "C", kickoff=KICKOFF + timedelta(days=5)),
        game("g3", "A", "D", kickoff=KICKOFF + timedelta(days=19)),
    ]
    result = compute_features(games)
    assert values(result, "g2")["short_week_home"] == 1.0
    assert values(result, "g2")["post_bye_home"] == 0.0
    assert values(result, "g3")["short_week_home"] == 0.0
    assert values(result, "g3")["post_bye_home"] == 1.0
    assert values(result, "g2")["rest_days_home"] == pytest.approx(5.0)


def test_elo_update_ordering_is_strictly_after_completion() -> None:
    config = FeatureConfig(game_duration=timedelta(hours=2))
    games = [
        game("g1", "A", "B", kickoff=KICKOFF, home_score=40, away_score=0),
        game("g2", "C", "D", kickoff=KICKOFF + timedelta(hours=2)),
        game("g3", "A", "F", kickoff=KICKOFF + timedelta(hours=2, seconds=1)),
    ]
    result = compute_features(games, config=config)
    # g2 starts exactly at g1's completion, which is not "strictly before", so
    # its Elo must be the season-start rating plus home field.
    assert values(result, "g2")["elo_home"] == pytest.approx(1565.0)
    assert values(result, "g2")["elo_away"] == pytest.approx(1500.0)
    # g3 starts one second later and sees A's result.
    assert values(result, "g3")["elo_home"] > 1500.0
    assert values(result, "g2")["elo_diff"] == pytest.approx(65.0)


def test_spread_probability_mapping() -> None:
    assert spread_probability(0.0) == pytest.approx(0.5)
    assert spread_probability(7.0) == pytest.approx(0.698, abs=0.01)
    assert spread_probability(14.0) > spread_probability(3.0)
    with pytest.raises(ValueError):
        spread_probability(-1.0)


def test_market_resolution_priority_and_probability_sources() -> None:
    kickoff = KICKOFF
    odds = OddsInfo(
        provider="ESPN Bet",
        favorite_team_id="A",
        spread_open=-7.0,
        favorite_source=FavoriteSource.ESPN_OPEN,
        line_provider="ESPN Bet",
        market_prob=None,
        market_prob_source=MarketProbSource.UNAVAILABLE,
        known_at=kickoff - timedelta(hours=72),
    )
    espn_game = game("g1", "A", "B", odds=odds)
    market = resolve_market(
        espn_game,
        strength_diff=-100.0,
        state_known=kickoff - timedelta(days=7),
    )
    assert market.favorite_team_id == "A"
    assert market.favorite_source is FavoriteSource.ESPN_OPEN
    assert market.market_prob_source is MarketProbSource.SPREAD_MAPPED
    assert market.market_prob == pytest.approx(0.698, abs=0.01)
    assert market.line_provider == "ESPN Bet"

    cfbd = resolve_market(
        game("g2", "A", "B", odds=odds, cfbd_spread_open=10.0, cfbd_line_provider="consensus"),
        strength_diff=100.0,
        state_known=kickoff - timedelta(days=7),
    )
    assert cfbd.favorite_team_id == "B"
    assert cfbd.favorite_source is FavoriteSource.CFBD_OPEN
    assert cfbd.line_provider == "consensus"
    assert cfbd.spread_open == pytest.approx(10.0)

    proxy = resolve_market(
        game("g3", "A", "B"),
        strength_diff=25.0,
        state_known=kickoff - timedelta(days=7),
    )
    assert proxy.favorite_source is FavoriteSource.STRENGTH_PROXY
    assert proxy.market_prob_source is MarketProbSource.UNAVAILABLE
    assert proxy.market_prob is None
    assert proxy.line_provider is None


def test_moneyline_probability_is_retained_and_admitted() -> None:
    odds = OddsInfo(
        provider="DraftKings",
        favorite_team_id="A",
        spread_open=-3.0,
        favorite_source=FavoriteSource.ESPN_OPEN,
        line_provider="DraftKings",
        market_prob=0.67,
        market_prob_source=MarketProbSource.MONEYLINE,
        known_at=KICKOFF - timedelta(hours=72),
    )
    market = resolve_market(
        game("g1", "A", "B", odds=odds),
        strength_diff=0.0,
        state_known=KICKOFF - timedelta(days=7),
    )
    assert market.market_prob == pytest.approx(0.67)
    assert market.market_prob_source is MarketProbSource.MONEYLINE


def test_rank_delta_and_look_ahead_use_earlier_week_ranks() -> None:
    week1 = KICKOFF
    week2 = KICKOFF + timedelta(days=7)
    known1 = week1 - timedelta(hours=1)
    known2 = week2 - timedelta(hours=1)
    games = [
        game(
            "g1",
            "A",
            "C",
            kickoff=week1,
            home_rank=5,
            away_rank=10,
            rank_known_at=known1,
        ),
        game(
            "g2",
            "A",
            "C",
            kickoff=week2,
            week=2,
            home_rank=3,
            away_rank=8,
            rank_known_at=known2,
        ),
    ]
    result = compute_features(games)
    row = values(result, "g2")
    assert row["rank_delta_home"] == pytest.approx(2.0)
    assert row["rank_delta_away"] == pytest.approx(2.0)
    first = values(result, "g1")
    assert first["look_ahead_rank_home"] == pytest.approx(10.0)
    assert first["look_ahead_rank_away"] == pytest.approx(5.0)
    assert first["is_ranked_home"] == 1.0
    assert known(result, "g1")["rank_home"] == known1


def test_permuting_input_order_does_not_change_features() -> None:
    games = [
        game(f"g{index}", f"H{index}", f"A{index}", kickoff=KICKOFF + timedelta(days=index))
        for index in range(6)
    ]
    baseline = compute_features(games)
    shuffled = list(games)
    random.Random(7).shuffle(shuffled)
    permuted = compute_features(shuffled)
    assert baseline.rows == permuted.rows
    assert baseline.fields == permuted.fields
    assert baseline.labels == permuted.labels


def test_deleting_post_cutoff_results_leaves_earlier_features_identical() -> None:
    games = [
        game(
            f"g{index}",
            f"H{index % 3}",
            f"A{index % 4}",
            kickoff=KICKOFF + timedelta(days=7 * index),
        )
        for index in range(9)
    ]
    cutoff = KICKOFF + timedelta(days=35)
    full = compute_features(games)
    # The schedule and future opponent are pre-game facts; only post-cutoff
    # *results* are removed. Look-ahead therefore stays fixed while no result
    # after the cutoff can influence an earlier feature.
    trimmed_games = [
        (
            replace(row, home_score=None, away_score=None, status="scheduled")
            if row.kickoff >= cutoff
            else row
        )
        for row in games
    ]
    trimmed = compute_features(trimmed_games)

    kept = {row.game_id for row in trimmed_games if row.kickoff < cutoff}
    assert {row.game_id for row in full.rows if row.game_id in kept} == kept
    for row in full.rows:
        if row.game_id in kept:
            assert row in trimmed.rows


def test_sentinel_post_kickoff_result_does_not_change_earlier_features() -> None:
    earlier = [
        game("g1", "A", "B", kickoff=KICKOFF, home_score=28, away_score=7),
        game("g2", "C", "D", kickoff=KICKOFF, home_score=21, away_score=14),
        game("g3", "A", "C", kickoff=KICKOFF + timedelta(days=7)),
    ]
    baseline = compute_features(earlier)
    poisoned = [
        replace(row, home_score=99, away_score=0) if row.game_id == "g3" else row for row in earlier
    ]
    with_sentinel = compute_features(poisoned)
    assert [row for row in with_sentinel.rows if row.game_id != "g3"] == [
        row for row in baseline.rows if row.game_id != "g3"
    ]


def test_splits_are_disjoint_ordered_and_enforced() -> None:
    assert split_for_season(2021) is Split.DEV
    assert split_for_season(2023) is Split.DEV
    assert split_for_season(2024) is Split.VAL
    assert split_for_season(2025) is Split.TEST
    with pytest.raises(ValueError):
        split_for_season(2020)
    assert_disjoint_order()
    assert assignments()[Split.DEV].seasons == (2021, 2022, 2023)
    assert split_counts([2021, 2023, 2024, 2025]) == {"dev": 2, "val": 1, "test": 1}

    with pytest.raises(AssertionError):
        assert_disjoint_order(
            {Split.DEV: (2021, 2022, 2023), Split.VAL: (2023, 2024), Split.TEST: (2025,)}
        )
    with pytest.raises(AssertionError):
        assert_disjoint_order(
            {Split.DEV: (2021, 2022, 2023), Split.VAL: (2025,), Split.TEST: (2024,)}
        )
    with pytest.raises(AssertionError):
        assert_pre_cutoff([(2024, KICKOFF)], Split.DEV)
    with pytest.raises(AssertionError):
        assert_split_boundaries(
            [
                (Split.DEV, KICKOFF),
                (Split.VAL, KICKOFF - timedelta(days=1)),
                (Split.TEST, KICKOFF + timedelta(days=400)),
            ]
        )
