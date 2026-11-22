"""CLI for P3: build leakage-safe features, market context, and labels.

Usage::

    python -m cfb_upset.pipelines.build_features
    python -m cfb_upset.pipelines.build_features --seasons 2021 2022 2023 2024 2025

The command reads the P2 corpus, computes features only from prior completed
games, writes ``game_features`` and derived ``game_fields`` rows, and emits a
wide ``data/features_v1.parquet`` plus a separate evaluation-only
``data/labels_v1.parquet``. A leakage or unknown-policy field fails the run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from cfb_upset.contracts import OddsInfo, TeamInfo, VenueInfo
from cfb_upset.domain.feature_report import build_feature_report, write_feature_report
from cfb_upset.domain.features import (
    FeatureConfig,
    FeatureGame,
    compute_features,
)
from cfb_upset.domain.splits import (
    assert_disjoint_order,
    assert_pre_cutoff,
    assert_split_boundaries,
    split_for_season,
)
from cfb_upset.errors import CFBError
from cfb_upset.ids import SystemClock
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories, StoredFeature, StoredField
from cfb_upset.store.seed import seed_teams, seed_venues

DEFAULT_SEASONS = (2021, 2022, 2023, 2024, 2025)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build leakage-safe pre-game features")
    parser.add_argument("--db", default=None, help="SQLite path (defaults to SQLITE_PATH)")
    parser.add_argument("--seasons", nargs="+", type=int, default=list(DEFAULT_SEASONS))
    parser.add_argument("--season-type", type=int, default=2)
    parser.add_argument("--config", default="configs/features.yaml")
    parser.add_argument("--feature-version", default=None)
    parser.add_argument("--parquet", default="data/features_v1.parquet")
    parser.add_argument("--labels-parquet", default="data/labels_v1.parquet")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--limit-games", type=int, default=None)
    parser.add_argument(
        "--seed-offline",
        action="store_true",
        help="overlay the checked-in team/venue fallback CSV before computing",
    )
    parser.add_argument(
        "--live-venues",
        action="store_true",
        help="overlay CFBD /venues (requires CFBD_API_KEY) before computing",
    )
    parser.add_argument(
        "--cfbd-lines",
        action="store_true",
        help="fetch CFBD open lines per season/week and cache them in game_fields",
    )
    return parser


def load_feature_games(
    repositories: Repositories,
    *,
    seasons: list[int],
    season_type: int = 2,
    limit: int | None = None,
) -> tuple[list[FeatureGame], dict[str, VenueInfo]]:
    stored = [
        game
        for game in repositories.games.list(fbs_only=True)
        if game.season in seasons and game.season_type == season_type
    ]
    if limit is not None:
        stored = stored[:limit]
    field_rows = repositories.coverage.fields(seasons=seasons, season_types=[season_type])
    by_game: dict[str, dict[str, Any]] = {}
    for row in field_rows:
        fields = by_game.setdefault(row.game_id, {})
        if row.field_name == "odds":
            # CFBD open lines are the primary source (D4); keep them over the
            # ESPN odds row even though ``espn`` sorts later.
            if "odds" not in fields or row.source == "cfbd_open":
                fields["odds"] = row
        else:
            fields[row.field_name] = row

    games: list[FeatureGame] = []
    for game in stored:
        fields = by_game.get(game.game_id, {})
        home_rank: int | None = None
        away_rank: int | None = None
        rank_known = None
        if "home" in fields:
            home = TeamInfo.model_validate(fields["home"].value)
            home_rank = home.rank
            if home_rank is not None:
                rank_known = _later(rank_known, fields["home"].known_at_utc)
        if "away" in fields:
            away = TeamInfo.model_validate(fields["away"].value)
            away_rank = away.rank
            if away_rank is not None:
                rank_known = _later(rank_known, fields["away"].known_at_utc)
        odds = None
        if "odds" in fields:
            try:
                odds = OddsInfo.model_validate(fields["odds"].value)
            except ValueError:
                odds = None
        games.append(
            FeatureGame(
                game_id=game.game_id,
                season=game.season,
                week=game.week,
                season_type=game.season_type,
                kickoff=game.kickoff_utc,
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                neutral_site=game.neutral_site,
                conference_game=game.conference_game,
                venue_id=game.venue_id,
                status=game.status,
                home_score=game.home_score,
                away_score=game.away_score,
                home_rank=home_rank,
                away_rank=away_rank,
                rank_known_at=rank_known,
                odds=odds,
            )
        )
    venues = {venue.venue_id: venue for venue in repositories.venues.list() if venue.venue_id}
    return games, venues


def build_features(args: argparse.Namespace) -> int:
    clock = SystemClock()
    database = Database(args.db)
    database.initialize()
    repositories = Repositories(database)

    if args.seed_offline:
        seed_teams(repositories)
        seed_venues(repositories)
    if args.live_venues:
        _seed_live_venues(repositories)
    if args.cfbd_lines:
        _fetch_cfbd_odds(repositories, seasons=list(args.seasons), season_type=args.season_type)

    config = FeatureConfig.from_yaml(args.config) if Path(args.config).exists() else FeatureConfig()
    if args.feature_version:
        config = replace(config, feature_version=args.feature_version)

    games, venues = load_feature_games(
        repositories,
        seasons=list(args.seasons),
        season_type=args.season_type,
        limit=args.limit_games,
    )
    if not games:
        print("no games found; run the P2 ingest first", file=sys.stderr)
        return 1

    result = compute_features(games, venues=venues, config=config)
    if not result.audit.ok:
        print(
            f"leakage audit FAILED: {result.audit.leaked} leaked rows, "
            f"unknown fields: {result.audit.unknown_fields}",
            file=sys.stderr,
        )
        for violation in result.audit.violations[:10]:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    _assert_splits(result)
    _write_rows(repositories, result, version=config.feature_version, fetched_at=clock.now())
    _write_parquet(result, config=config, path=Path(args.parquet), labels=Path(args.labels_parquet))

    report = build_feature_report(result, generated_at=clock.now())
    markdown, payload = write_feature_report(report, args.report_dir)

    print(f"games: {result.games} · feature rows: {len(result.rows)}")
    print(f"feature version: {config.feature_version}")
    print(
        "market: "
        + ", ".join(f"{name}={count}" for name, count in sorted(report.market_sources.items()))
    )
    print(
        "market prob: "
        + ", ".join(f"{name}={count}" for name, count in sorted(report.market_prob_sources.items()))
    )
    print(f"splits: {report.split_counts}")
    print(
        f"labels: {report.labels} (upsets {report.upsets}, unavailable {report.label_unavailable})"
    )
    print(f"leakage: {'PASS' if report.ok else 'FAIL'}")
    print(f"parquet: {args.parquet} · labels: {args.labels_parquet}")
    print(f"report: {markdown} · {payload}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return build_features(args)
    except CFBError as exc:
        print(f"feature build failed: {exc}", file=sys.stderr)
        return 1


def _write_rows(
    repositories: Repositories,
    result: Any,
    *,
    version: str,
    fetched_at: datetime,
) -> None:
    repositories.game_features.delete_version(version)
    repositories.game_fields.delete_source(version)
    repositories.game_features.record_many(
        [
            StoredFeature(
                game_id=row.game_id,
                feature_name=row.feature_name,
                value=row.value,
                known_at_utc=row.known_at,
                feature_version=version,
            )
            for row in result.rows
        ]
    )
    repositories.game_fields.record_many(
        [
            StoredField(
                game_id=derived.game_id,
                field_name=derived.field_name,
                value=derived.value,
                known_at_utc=derived.known_at,
                source=version,
                source_url="feature_builder",
                fetched_at_utc=fetched_at,
            )
            for derived in result.fields
        ]
    )


def _write_parquet(result: Any, *, config: FeatureConfig, path: Path, labels: Path) -> None:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - pandas is a runtime dependency
        raise CFBError("pandas is required to write the features parquet") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    labels.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(result.wide_rows)
    frame["split"] = [split_for_season(int(season)).value for season in frame["season"]]
    frame = frame.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    frame.to_parquet(path, index=False)

    label_frame = pd.DataFrame(
        [
            {
                "game_id": label.game_id,
                "season": label.season,
                "week": label.week,
                "split": split_for_season(label.season).value,
                "kickoff_utc": label.kickoff,
                "home_team_id": label.home_team_id,
                "away_team_id": label.away_team_id,
                "favorite_team_id": label.favorite_team_id,
                "favorite_source": label.favorite_source,
                "market_prob": label.market_prob,
                "upset": label.upset,
                "margin": label.margin,
            }
            for label in result.labels
        ]
    )
    if len(label_frame):
        label_frame["upset"] = label_frame["upset"].astype("boolean")
        label_frame["margin"] = label_frame["margin"].astype("Int64")
        label_frame = label_frame.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    label_frame.to_parquet(labels, index=False)


def _assert_splits(result: Any) -> None:
    assert_disjoint_order()
    grouped: dict[Any, list[tuple[int, datetime]]] = {}
    for row in result.wide_rows:
        season = int(row["season"])
        grouped.setdefault(split_for_season(season), []).append((season, row["kickoff_utc"]))
    for split, rows in grouped.items():
        assert_pre_cutoff(rows, split)
    boundaries = [
        (split_for_season(int(row["season"])), row["kickoff_utc"]) for row in result.wide_rows
    ]
    if len(grouped) == 3:
        assert_split_boundaries(boundaries)


def _seed_live_venues(repositories: Repositories) -> None:
    async def run() -> None:
        from cfb_upset.adapters.cfbd import CfbdAdapter

        adapter = CfbdAdapter()
        venues = await adapter.fetch_venues()
        seed_venues(repositories, cfbd_venues=venues)

    try:
        asyncio.run(run())
    except Exception as exc:  # pragma: no cover - live path
        print(f"warning: CFBD venue seed skipped ({exc})", file=sys.stderr)


def _fetch_cfbd_odds(
    repositories: Repositories,
    *,
    seasons: list[int],
    season_type: int = 2,
) -> int:
    """Fetch CFBD open lines and cache them as ``game_fields`` (source=cfbd_open)."""

    from cfb_upset.adapters.cfbd import CfbdAdapter
    from cfb_upset.config import get_settings

    stored = {
        game.game_id: game
        for game in repositories.games.list()
        if game.season in seasons and game.season_type == season_type
    }
    week_keys = sorted(
        {(game.season, game.week) for game in stored.values() if game.week is not None}
    )
    if not week_keys:
        return 0
    adapter = CfbdAdapter()
    semaphore = asyncio.Semaphore(max(1, get_settings().cfbd_max_concurrency))
    failures: list[str] = []

    async def fetch_week(season: int, week: int):
        async with semaphore:
            return season, week, await adapter.fetch_lines(season=season, week=week)

    async def run() -> list[Any]:
        results = await asyncio.gather(
            *(fetch_week(season, week) for season, week in week_keys),
            return_exceptions=True,
        )
        return list(results)

    try:
        results = asyncio.run(run())
    except Exception as exc:  # pragma: no cover - live path
        print(f"warning: CFBD lines skipped ({exc})", file=sys.stderr)
        return 0

    stamp = SystemClock().now()
    rows: list[StoredField] = []
    for result in results:
        if isinstance(result, BaseException):
            failures.append(str(result))
            continue
        season, week, games = result
        for game in games:
            scheduled = stored.get(game.game_id)
            if scheduled is None:
                continue
            odds = adapter.pick_odds(
                game,
                home_team_id=scheduled.home_team_id,
                away_team_id=scheduled.away_team_id,
                kickoff=scheduled.kickoff_utc,
            )
            if odds is None:
                continue
            rows.append(
                StoredField(
                    game_id=game.game_id,
                    field_name="odds",
                    value=odds.model_dump(mode="json"),
                    known_at_utc=odds.known_at,
                    source="cfbd_open",
                    source_url=f"cfbd://lines/{season}/{week}",
                    fetched_at_utc=stamp,
                )
            )
    repositories.game_fields.record_many(rows)
    print(f"CFBD open lines cached: {len(rows)} games ({len(week_keys) - len(failures)} weeks)")
    if failures:
        print(f"warning: {len(failures)} CFBD week calls failed", file=sys.stderr)
    return len(rows)


def _later(current: datetime | None, candidate: datetime) -> datetime:
    if current is None or candidate > current:
        return candidate
    return current


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
