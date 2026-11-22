"""Integration tests for the P3 build: DB rows, parquet, labels, and leakage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

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
from cfb_upset.domain.feature_report import build_feature_report, write_feature_report
from cfb_upset.domain.features import FeatureConfig, FeatureGame, compute_features
from cfb_upset.domain.leakage import LeakageError
from cfb_upset.pipelines.build_features import build_features, build_parser, load_feature_games
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories

BASE = datetime(2021, 9, 4, 16, 0, tzinfo=UTC)


def provenance(*, known_at: datetime, source: str = "test") -> Provenance:
    return Provenance(source=source, known_at=known_at, fetched_at=known_at)


def record(
    game_id: str,
    season: int,
    week: int,
    kickoff: datetime,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    *,
    home_rank: int | None = None,
    away_rank: int | None = None,
    rank_known_at: datetime | None = None,
    venue: VenueInfo | None = None,
    odds: OddsInfo | None = None,
) -> HistoricalGameRecord:
    pre = provenance(known_at=kickoff - timedelta(days=7))
    post = provenance(known_at=kickoff, source="test_postgame")
    winner = home if home_score > away_score else away
    fields = {
        "game_id": pre,
        "season": pre,
        "week": pre,
        "kickoff_utc": pre,
        "home": provenance(known_at=rank_known_at or (kickoff - timedelta(days=7))),
        "away": provenance(known_at=rank_known_at or (kickoff - timedelta(days=7))),
        "neutral_site": pre,
        "conference_game": pre,
        "status": pre,
        "home_score": post,
        "away_score": post,
        "winner_team_id": post,
    }
    if venue is not None:
        fields["venue"] = pre
    if odds is not None:
        fields["odds"] = provenance(known_at=odds.known_at)
    return HistoricalGameRecord(
        game_id=game_id,
        season=season,
        week=week,
        kickoff_utc=kickoff,
        home=TeamInfo(team_id=home, school=home, rank=home_rank),
        away=TeamInfo(team_id=away, school=away, rank=away_rank),
        venue=venue,
        neutral_site=False,
        conference_game=True,
        status=GameStatus.FINAL,
        home_score=home_score,
        away_score=away_score,
        winner_team_id=winner,
        odds=odds,
        field_provenance=fields,
        fetched_at=kickoff + timedelta(hours=5),
    )


def seed_corpus(repositories: Repositories) -> None:
    venue = VenueInfo(
        venue_id="V1",
        name="Test Field",
        lat=40.0,
        lon=-80.0,
        tz="America/New_York",
        altitude_m=100.0,
    )
    odds = OddsInfo(
        provider="ESPN Bet",
        favorite_team_id="A",
        spread_open=-7.0,
        favorite_source=FavoriteSource.ESPN_OPEN,
        line_provider="ESPN Bet",
        market_prob=None,
        market_prob_source=MarketProbSource.UNAVAILABLE,
        known_at=BASE - timedelta(hours=72),
    )
    records = [
        record("g1", 2021, 1, BASE, "A", "B", 28, 7, venue=venue, odds=odds),
        record("g2", 2021, 1, BASE + timedelta(hours=1), "C", "D", 21, 14, venue=venue),
        record(
            "g3",
            2024,
            1,
            BASE + timedelta(days=365 * 3),
            "A",
            "C",
            24,
            17,
            home_rank=3,
            away_rank=9,
            rank_known_at=BASE + timedelta(days=365 * 3) - timedelta(hours=1),
            venue=venue,
        ),
        record("g4", 2025, 1, BASE + timedelta(days=365 * 4), "B", "D", 10, 31, venue=venue),
    ]
    for item in records:
        repositories.games.upsert(item)


def test_load_feature_games_reads_rank_and_odds(tmp_path: Path) -> None:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    repositories = Repositories(database)
    seed_corpus(repositories)

    games, venues = load_feature_games(repositories, seasons=[2021, 2024, 2025])
    assert len(games) == 4
    assert "V1" in venues
    by_id = {game.game_id: game for game in games}
    assert by_id["g3"].home_rank == 3
    assert by_id["g3"].away_rank == 9
    assert by_id["g3"].rank_known_at is not None
    assert by_id["g1"].odds is not None
    assert by_id["g1"].odds.favorite_source is FavoriteSource.ESPN_OPEN


def test_build_features_writes_rows_parquet_labels_and_zero_leaks(tmp_path: Path) -> None:
    db_path = tmp_path / "cfb.db"
    database = Database(db_path)
    database.initialize()
    repositories = Repositories(database)
    seed_corpus(repositories)
    database.close()

    features_path = tmp_path / "features.parquet"
    labels_path = tmp_path / "labels.parquet"
    args = build_parser().parse_args(
        [
            "--db",
            str(db_path),
            "--seasons",
            "2021",
            "2024",
            "2025",
            "--parquet",
            str(features_path),
            "--labels-parquet",
            str(labels_path),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )
    assert build_features(args) == 0

    database = Database(db_path)
    repositories = Repositories(database)
    feature_count = repositories.game_features.count_by_version("features_v1")
    assert feature_count > 0
    assert feature_count % 4 == 0

    connection = sqlite3.connect(db_path)
    leaked = connection.execute(
        """
        SELECT COUNT(*) FROM game_features f JOIN games g ON g.game_id = f.game_id
        WHERE f.known_at_utc >= g.kickoff_utc
        """
    ).fetchone()[0]
    assert leaked == 0
    unknown_sources = connection.execute(
        "SELECT COUNT(*) FROM game_fields WHERE source = 'features_v1'"
    ).fetchone()[0]
    assert unknown_sources > 0
    connection.close()

    frame = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)
    assert {"game_id", "split", "wins_home", "elo_diff", "market_prob_home"} <= set(frame.columns)
    assert "upset" not in frame.columns
    assert {"upset", "margin", "favorite_source"} <= set(labels.columns)
    assert len(labels) == 4
    assert set(frame["split"]) == {"dev", "val", "test"}
    assert (tmp_path / "reports").exists()
    assert any((tmp_path / "reports").iterdir())

    # Idempotent rebuild: the version is replaced, not duplicated.
    assert build_features(args) == 0
    database = Database(db_path)
    assert Repositories(database).game_features.count_by_version("features_v1") == feature_count
    database.close()


def test_report_marks_coverage_and_leakage() -> None:
    games = [
        FeatureGame(
            game_id="g1",
            season=2021,
            week=1,
            season_type=2,
            kickoff=BASE,
            home_team_id="A",
            away_team_id="B",
            neutral_site=False,
            conference_game=True,
            venue_id=None,
            status="final",
            home_score=28,
            away_score=7,
        )
    ]
    result = compute_features(games, config=FeatureConfig())
    report = build_feature_report(result, generated_at=BASE)
    assert report.ok
    assert report.games == 1
    assert report.market_sources == {"strength_proxy": 1}
    assert report.market_prob_sources == {"unavailable": 1}
    assert report.split_counts == {"dev": 1, "val": 0, "test": 0}
    markdown = report.to_markdown()
    assert "leakage: **PASS**" in markdown
    assert "wins_home" in markdown

    with pytest.raises(LeakageError):
        compute_features(
            [
                FeatureGame(
                    game_id="bad",
                    season=2021,
                    week=1,
                    season_type=2,
                    kickoff=BASE,
                    home_team_id="A",
                    away_team_id="B",
                    neutral_site=False,
                    conference_game=True,
                    venue_id=None,
                    status="final",
                    home_score=1,
                    away_score=0,
                    rank_known_at=BASE,
                )
            ]
        )


def test_report_writer_is_deterministic(tmp_path: Path) -> None:
    games = [
        FeatureGame(
            game_id="g1",
            season=2021,
            week=1,
            season_type=2,
            kickoff=BASE,
            home_team_id="A",
            away_team_id="B",
            neutral_site=False,
            conference_game=True,
            venue_id=None,
            status="final",
            home_score=28,
            away_score=7,
        )
    ]
    report = build_feature_report(compute_features(games), generated_at=BASE)
    first = write_feature_report(report, tmp_path)
    second = write_feature_report(report, tmp_path)
    assert first == second
    assert first[0].read_text() == second[0].read_text()
