"""CLI for Pipeline 1: build the historical FBS-vs-FBS corpus.

Usage::

    python -m cfb_upset.pipelines.ingest_corpus --seasons 2021 2022 2023 2024 2025
    python -m cfb_upset.pipelines.ingest_corpus --seasons 2024 --weeks 1 2 --resume

The command is idempotent (``games`` is keyed by ``game_id``); ``--resume``
additionally skips any game already stored so a re-run performs no duplicate
summary/odds fetches.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.agents.base import AgentContext
from cfb_upset.agents.data_orchestrator import DataOrchestrator, IngestOptions
from cfb_upset.config import get_settings
from cfb_upset.domain.coverage import write_coverage
from cfb_upset.errors import CFBError
from cfb_upset.ids import SystemClock, new_ulid
from cfb_upset.observability.budget import Budget
from cfb_upset.observability.trace import JsonlTraceSink, SqliteEventSink, Trace
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest the historical CFB corpus")
    parser.add_argument("--seasons", nargs="+", type=int, required=True)
    parser.add_argument("--weeks", nargs="+", type=int, default=None)
    parser.add_argument("--season-type", type=int, default=2)
    parser.add_argument("--include-postseason", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--db", default=None, help="SQLite path (defaults to SQLITE_PATH)")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit-games", type=int, default=None)
    parser.add_argument("--budget-seconds", type=float, default=0.0)
    parser.add_argument("--report-dir", default="reports")
    return parser


async def _ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    clock = SystemClock()
    run_id = new_ulid(clock)
    database = Database(args.db)
    dataset = database.initialize()
    repositories = Repositories(database)
    trace = Trace(
        run_id=run_id,
        clock=clock,
        sinks=[JsonlTraceSink(run_id=run_id), SqliteEventSink(repositories)],
    )
    budget = Budget(
        name="ingest",
        deadline_s=args.budget_seconds if args.budget_seconds > 0 else None,
    )
    context = AgentContext.create(
        repositories,
        trace=trace,
        budget=budget,
        clock=clock,
        settings=settings,
        worker_count=args.workers,
    )
    options = IngestOptions(
        seasons=args.seasons,
        weeks=args.weeks,
        season_type=args.season_type,
        include_postseason=args.include_postseason,
        resume=args.resume,
        batch_size=args.batch_size,
        limit_games=args.limit_games,
    )

    print(f"run: {run_id}")
    print(f"database: {database.resolved_path()} (applied: {', '.join(dataset) or 'none'})")
    print(
        f"seasons: {args.seasons} · types: {options.season_types()} · "
        f"workers: {context.worker_count}"
    )

    try:
        async with EspnAdapter(clock=clock) as adapter:
            orchestrator = DataOrchestrator(context, adapter)
            outcome = await orchestrator.run(options)
    finally:
        trace.close()
        database.close()

    report = outcome.report
    markdown_path, json_path = write_coverage(outcome.coverage, args.report_dir)
    print(
        "games: "
        f"requested={report.games_requested} stored={report.games_stored} "
        f"quarantined={report.quarantined} duplicates={report.duplicates_removed} "
        f"skipped_existing={outcome.skipped_existing}"
    )
    print(f"odds unavailable: {outcome.odds_unavailable}")
    if outcome.failed_weeks:
        print(f"weeks with provider failures: {len(outcome.failed_weeks)}")
        for failure in outcome.failed_weeks[:10]:
            print(f"  - {failure}")
    leakage = outcome.coverage.leaked_admissible_fields
    print(f"leakage: {'PASS' if leakage == 0 else f'FAIL ({leakage} fields)'}")
    print(f"coverage: {markdown_path} · {json_path}")

    if report.games_stored + outcome.skipped_existing == 0 or leakage != 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_ingest(args))
    except CFBError as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
