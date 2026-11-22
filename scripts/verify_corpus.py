"""P2 gate verifier: dedupe, leakage, and an independent per-season count.

The independent count re-enumerates the live scoreboard (group 80) and applies
the same FBS-vs-FBS definition, without reading the stored corpus. The plan
allows +/-5% per season.

    python scripts/verify_corpus.py --db data/cfb.db --seasons 2021 2022 2023 2024 2025
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow ``python scripts/verify_corpus.py`` from a fresh checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfb_upset.adapters.espn import FBS_GROUP_ID, EspnAdapter  # noqa: E402
from cfb_upset.contracts import GameStatus  # noqa: E402
from cfb_upset.domain.coverage import build_coverage  # noqa: E402
from cfb_upset.ids import SystemClock  # noqa: E402
from cfb_upset.store.db import Database  # noqa: E402
from cfb_upset.store.repositories import Repositories  # noqa: E402


async def independent_counts(
    adapter: EspnAdapter,
    seasons: list[int],
    season_type: int,
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for season in seasons:
        fbs = set(await adapter.fetch_group_team_ids(season=season, season_type=season_type))
        weeks = await adapter.fetch_week_numbers(season=season, season_type=season_type)
        game_ids: set[str] = set()
        for week in weeks:
            records = await adapter.fetch_scoreboard(
                season=season,
                week=week,
                season_type=season_type,
                groups=FBS_GROUP_ID,
                limit=500,
            )
            for record in records:
                if record.status is not GameStatus.FINAL:
                    continue
                if record.home.team_id not in fbs or record.away.team_id not in fbs:
                    continue
                game_ids.add(record.game_id)
        counts[season] = len(game_ids)
        print(f"independent {season}: {len(game_ids)} games", flush=True)
    return counts


async def verify(args: argparse.Namespace) -> int:
    database = Database(args.db)
    repositories = Repositories(database)
    clock = SystemClock()
    season_types = [args.season_type]

    rows, distinct = repositories.coverage.game_id_counts(
        seasons=args.seasons, season_types=season_types
    )
    dedupe_ok = rows == distinct
    print(f"dedupe: {'PASS' if dedupe_ok else 'FAIL'} (rows={rows} distinct={distinct})")

    coverage = build_coverage(
        repositories.coverage.games(seasons=args.seasons, season_types=season_types),
        repositories.coverage.fields(seasons=args.seasons, season_types=season_types),
        seasons=args.seasons,
        season_types=season_types,
        generated_at=clock.now(),
    )
    leakage_ok = coverage.leaked_admissible_fields == 0
    print(
        f"leakage: {'PASS' if leakage_ok else 'FAIL'} "
        f"({coverage.leaked_admissible_fields} admissible fields at/after kickoff)"
    )

    gaps = repositories.coverage.provenance_gaps(seasons=args.seasons, season_types=season_types)
    provenance_ok = gaps == 0
    print(f"provenance: {'PASS' if provenance_ok else 'FAIL'} ({gaps} incomplete fields)")

    stored = {season: count for season, count in coverage.games_by_season.items()}
    independent: dict[int, int] = {}
    if not args.skip_live:
        async with EspnAdapter(clock=clock) as adapter:
            independent = await independent_counts(adapter, args.seasons, args.season_type)

    print("")
    print("| Season | Stored | Independent | Delta | Within +/-5% |")
    print("| --- | ---: | ---: | ---: | --- |")
    counts_ok = True
    for season in args.seasons:
        stored_count = stored.get(season, 0)
        expected = independent.get(season)
        if expected is None:
            print(f"| {season} | {stored_count} | n/a | n/a | skipped |")
            continue
        delta = (stored_count - expected) / expected if expected else 0.0
        within = abs(delta) <= args.tolerance
        counts_ok = counts_ok and within
        print(
            f"| {season} | {stored_count} | {expected} | {delta:+.1%} | "
            f"{'yes' if within else 'NO'} |"
        )

    total = sum(stored.values())
    print("")
    print(f"total stored: {total}")
    passed = dedupe_ok and leakage_ok and provenance_ok and counts_ok
    print(f"corpus gate: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the P2 corpus gate")
    parser.add_argument("--db", default="data/cfb.db")
    parser.add_argument("--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025])
    parser.add_argument("--season-type", type=int, default=2)
    parser.add_argument("--tolerance", type=float, default=0.05)
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="only run the DB-side dedupe/leakage checks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(verify(args))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
