"""Coverage aggregation and artifact writing (P2.6 / R32)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cfb_upset.domain.coverage import build_coverage, write_coverage
from cfb_upset.store.repositories import CoverageFieldRow, CoverageGameRow

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
KICKOFF = datetime(2024, 9, 28, 23, 30, tzinfo=UTC)


def game(game_id: str, *, home: str = "1", away: str = "2") -> CoverageGameRow:
    return CoverageGameRow(
        game_id=game_id,
        season=2024,
        week=5,
        season_type=2,
        kickoff_utc=KICKOFF,
        home_team_id=home,
        away_team_id=away,
        is_fbs_vs_fbs=True,
    )


def field(
    game_id: str,
    name: str,
    value: object,
    *,
    known_at: datetime = KICKOFF,
    source: str = "espn",
) -> CoverageFieldRow:
    return CoverageFieldRow(
        game_id=game_id,
        field_name=name,
        source=source,
        value=value,
        known_at_utc=known_at,
    )


def test_team_denominator_is_games_involving_team() -> None:
    games = [game("g1"), game("g2", home="3", away="4")]
    fields = [field("g1", "venue", {"name": "Stadium"})]
    report = build_coverage(games, fields, seasons=[2024], season_types=[2], generated_at=NOW)
    assert report.by_team["1"].games == 1
    assert report.by_team["1"].fields["venue"].pct == 100.0
    assert report.overall["venue"].pct == 50.0


def test_missing_odds_are_counted_as_unavailable() -> None:
    games = [game("g1"), game("g2", home="3", away="4")]
    fields = [
        field(
            "g1",
            "odds",
            {"favorite_source": "espn_open", "market_prob_source": "moneyline"},
            known_at=KICKOFF.replace(day=25),
        )
    ]
    report = build_coverage(games, fields, seasons=[2024], season_types=[2], generated_at=NOW)
    assert report.favorite_sources == {"espn_open": 1, "unavailable": 1}
    assert report.leaked_admissible_fields == 0


def test_write_coverage_emits_markdown_and_json(tmp_path: Path) -> None:
    report = build_coverage(
        [game("g1")],
        [field("g1", "venue", {"name": "Stadium"}, known_at=KICKOFF.replace(day=20))],
        seasons=[2024],
        season_types=[2],
        generated_at=NOW,
    )
    markdown_path, json_path = write_coverage(report, tmp_path)
    assert markdown_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["total_games"] == 1
    assert payload["ok"] is True
    text = markdown_path.read_text()
    assert "Historical corpus coverage" in text
    assert "| `venue` | venue | 100.0%" in text
