"""ESPN fixture parity: scoreboard, summary, odds, rankings, groups."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.adapters.espn import EspnAdapter, american_to_probability
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.contracts import GameStatus, MarketProbSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def load(name: str) -> dict:
    return json.loads((FIXTURES / "espn" / name).read_text())


def test_scoreboard_parses_all_events_with_scores() -> None:
    adapter = EspnAdapter(FixtureTransport())
    records = adapter.parse_scoreboard(load("scoreboard_20251115.json"), fetched_at=NOW)
    assert len(records) == 3
    first = records[0]
    assert first.game_id == "401752900"
    assert first.season == 2025
    assert first.week == 12
    assert first.home.school == "Ohio State"
    assert first.away.school == "UCLA"
    assert first.home_score == 48
    assert first.away_score == 10
    assert first.winner_team_id == "194"
    assert first.status is GameStatus.FINAL
    assert first.venue is not None and first.venue.name == "Ohio Stadium"


def test_scoreboard_provenance_respects_leakage_policy() -> None:
    adapter = EspnAdapter(FixtureTransport())
    record = adapter.parse_scoreboard(load("scoreboard_20251115.json"), fetched_at=NOW)[0]
    assert record.field_provenance["home"].known_at <= record.kickoff_utc
    assert record.field_provenance["home_score"].known_at == record.kickoff_utc
    assert record.field_provenance["odds"].known_at < record.kickoff_utc


def test_future_scoreboard_parses_odds_and_ignores_weather() -> None:
    adapter = EspnAdapter(FixtureTransport())
    record = adapter.parse_scoreboard(load("scoreboard_20261128.json"), fetched_at=NOW)[0]
    assert record.status is GameStatus.SCHEDULED
    assert record.home_score is None and record.away_score is None
    assert record.odds is not None
    assert record.odds.favorite_team_id == "87"  # Notre Dame is the away favourite
    assert record.odds.spread == pytest.approx(-25.5)
    assert record.odds.line_provider == "DraftKings"
    assert record.odds.market_prob_source is MarketProbSource.UNAVAILABLE
    assert record.weather is None


def test_summary_parses_venue_and_box_score() -> None:
    adapter = EspnAdapter(FixtureTransport())
    record = adapter.parse_summary(load("summary_401628543.json"), fetched_at=NOW)
    assert record.game_id == "401628543"
    assert record.home.school == "Oregon"
    assert record.away.school == "Maryland"
    assert record.home_score == 39
    assert record.away_score == 18
    assert record.venue is not None and record.venue.name == "Autzen Stadium"
    assert set(record.team_stats) == {"120", "2483"}
    assert record.team_stats["2483"]


def test_core_odds_parses_open_and_moneyline_probability() -> None:
    adapter = EspnAdapter(FixtureTransport())
    payload = load("odds_401628543.json")
    odds = adapter.parse_odds(
        payload,
        home_team_id="2483",
        away_team_id="120",
        kickoff=datetime(2024, 11, 10, 0, 0, tzinfo=UTC),
        fetched_at=NOW,
    )
    assert odds is not None
    assert odds.provider == "ESPN BET"
    assert odds.favorite_team_id == "2483"
    assert odds.spread_open == pytest.approx(-25.0)
    assert odds.spread == pytest.approx(-24.0)
    assert odds.over_under == pytest.approx(57.5)
    assert odds.market_prob is not None and 0.0 < odds.market_prob < 1.0
    assert odds.market_prob_source is MarketProbSource.MONEYLINE
    assert odds.known_at == odds.known_at.astimezone(UTC)


def test_rankings_parses_ap_top_25() -> None:
    adapter = EspnAdapter(FixtureTransport())
    rankings = adapter.parse_rankings(load("rankings_2024_w10.json"))
    assert rankings.poll == "AP Poll"
    assert rankings.season == 2026
    assert rankings.week == 13
    assert rankings.ranks["61"] == 1
    assert len(rankings.ranks) == 5
    assert rankings.published_at is not None


def test_groups_parse_fbs_membership() -> None:
    adapter = EspnAdapter(FixtureTransport())
    groups = adapter.parse_groups(
        {
            "items": [
                {"id": "80", "name": "FBS", "teams": [{"id": "194"}, {"id": "26"}]},
                {"id": "5", "name": "Big Ten", "parent": {"id": "80"}, "teams": ["194"]},
            ]
        }
    )
    assert groups[0].group_id == "80"
    assert groups[0].team_ids == ["194", "26"]
    assert groups[1].parent_id == "80"


def test_american_odds_conversion() -> None:
    assert american_to_probability(-110) == pytest.approx(110 / 210)
    assert american_to_probability(150) == pytest.approx(100 / 250)


async def test_fetch_scoreboard_uses_fixture_transport() -> None:
    transport = FixtureTransport().add_json_file(
        "/scoreboard", FIXTURES / "espn" / "scoreboard_20251115.json"
    )
    adapter = EspnAdapter(transport)
    records = await adapter.fetch_scoreboard(dates="20251115")
    assert len(records) == 3
    assert transport.calls[0].url.startswith("/scoreboard")
