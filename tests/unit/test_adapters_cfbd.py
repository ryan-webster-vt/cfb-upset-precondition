"""CFBD fixture parity: open lines, provider preference, venues, and no-open."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.adapters.cfbd import (
    CfbdAdapter,
    CfbdGameLines,
    CfbdLine,
    american_to_probability,
)
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.contracts import FavoriteSource, MarketProbSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
KICKOFF = datetime(2025, 8, 23, 16, 0, tzinfo=UTC)


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / "cfbd" / name).read_text())


def test_parse_lines_preserves_identity_and_provider_rows() -> None:
    games = CfbdAdapter.parse_lines(load("lines_2025_w1.json"))
    assert len(games) == 3
    first = games[0]
    assert first.game_id == "401756847"
    assert first.season == 2025
    assert first.week == 1
    assert first.home_team == "Kansas"
    assert first.away_team == "Fresno State"
    assert first.is_fbs_vs_fbs
    assert [line.provider for line in first.lines] == ["DraftKings", "ESPN Bet", "Bovada"]
    assert first.lines[1].spread_open == pytest.approx(-13.5)


def test_pick_odds_uses_configured_provider_open_line() -> None:
    adapter = CfbdAdapter(FixtureTransport(), line_providers=["DraftKings"])
    game = CfbdAdapter.parse_lines(load("lines_2025_w1.json"))[0]
    odds = adapter.pick_odds(game, home_team_id="2305", away_team_id="278", kickoff=KICKOFF)
    assert odds is not None
    assert odds.provider == "DraftKings"
    assert odds.favorite_team_id == "2305"
    assert odds.spread_open == pytest.approx(-14.0)
    assert odds.spread == pytest.approx(-14.0)
    assert odds.over_under == pytest.approx(51.5)
    assert odds.favorite_source is FavoriteSource.CFBD_OPEN
    assert odds.market_prob_source is MarketProbSource.MONEYLINE
    assert odds.market_prob is not None
    assert odds.known_at < KICKOFF


def test_provider_names_match_with_underscores_or_spaces() -> None:
    game = CfbdAdapter.parse_lines(load("lines_2025_w1.json"))[0]
    adapter = CfbdAdapter(FixtureTransport(), line_providers=["ESPN_BET"])
    odds = adapter.pick_odds(game, home_team_id="2305", away_team_id="278", kickoff=KICKOFF)
    assert odds is not None
    assert odds.provider == "ESPN Bet"
    assert odds.spread_open == pytest.approx(-13.5)


def test_pick_odds_returns_none_when_no_configured_open_exists() -> None:
    adapter = CfbdAdapter(FixtureTransport(), line_providers=["consensus", "DraftKings"])
    games = CfbdAdapter.parse_lines(load("lines_2021_w1.json"))
    for game in games:
        assert adapter.pick_odds(game, home_team_id="1", away_team_id="2", kickoff=KICKOFF) is None


def test_pick_odds_handles_away_favourite_and_missing_moneyline() -> None:
    game = CfbdGameLines(
        game_id="g",
        season=2025,
        week=1,
        home_team="Home",
        away_team="Away",
        lines=[CfbdLine(provider="DraftKings", spread=2.5, spread_open=3.0)],
    )
    adapter = CfbdAdapter(FixtureTransport(), line_providers=["DraftKings"])
    odds = adapter.pick_odds(game, home_team_id="H", away_team_id="A", kickoff=KICKOFF)
    assert odds is not None
    assert odds.favorite_team_id == "A"
    assert odds.spread_open == pytest.approx(-3.0)
    assert odds.spread == pytest.approx(-2.5)
    assert odds.market_prob is None
    assert odds.market_prob_source is MarketProbSource.UNAVAILABLE


def test_parse_venues_converts_numeric_strings_and_keeps_nulls() -> None:
    venues = CfbdAdapter.parse_venues(load("venues.json"))
    assert len(venues) == 5
    by_id = {venue.venue_id: venue for venue in venues}
    assert by_id["218"].altitude_m == pytest.approx(1.718581796)
    assert by_id["218"].tz == "America/New_York"
    assert by_id["5938"].tz is None
    assert by_id["5938"].source == "cfbd"
    assert by_id["5938"].indoor is False


async def test_fetch_lines_and_venues_use_fixture_transport() -> None:
    transport = FixtureTransport().add_json_file("/lines", FIXTURES / "cfbd" / "lines_2025_w1.json")
    transport.add_json_file("/venues", FIXTURES / "cfbd" / "venues.json")
    adapter = CfbdAdapter(transport, base_url="https://cfbd.example", line_providers=["DraftKings"])

    games = await adapter.fetch_lines(season=2025, week=1)
    venues = await adapter.fetch_venues()

    assert len(games) == 3
    assert len(venues) == 5
    assert transport.calls[0].url.startswith("/lines?")
    assert "season=2025" in transport.calls[0].url
    assert "week=1" in transport.calls[0].url
    assert transport.calls[1].method == "GET"


async def test_non_success_response_is_not_silently_parsed() -> None:
    transport = FixtureTransport().add("/lines", {"error": "upstream"}, status_code=503)
    adapter = CfbdAdapter(transport, line_providers=["DraftKings"])
    with pytest.raises(ValueError, match="503"):
        await adapter.fetch_lines(season=2025, week=1)


def test_american_to_probability_conversion() -> None:
    assert american_to_probability(-550) == pytest.approx(550 / 650)
    assert american_to_probability(410) == pytest.approx(100 / 510)
