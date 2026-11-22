"""Data-Orchestrator for Pipeline 1 (historical corpus ingestion).

Responsibilities (P2.1-P2.2, P2.6):

1. resolve FBS membership per season from group 80;
2. enumerate seasons/types/weeks and keep only FBS-vs-FBS, completed games;
3. dedupe by ``game_id`` and partition deterministic batches across workers;
4. fetch each week's poll once, then let the workers fetch games concurrently;
5. validate/aggregate outcomes and emit an ``IngestReport`` plus a coverage
   report (``last_coverage``) built from what was actually stored.

The orchestrator never trusts the site scoreboard's ``season`` parameter: the
site API ignores it and would silently serve the current season (AD-034).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from cfb_upset.adapters.espn import FBS_GROUP_ID, EspnAdapter, Rankings
from cfb_upset.agents.base import AgentContext
from cfb_upset.agents.historical_stats_worker import (
    BatchOutcome,
    HistoricalStatsWorker,
    WeekContext,
)
from cfb_upset.contracts import GameIdBatch, GameStatus, HistoricalGameRecord, IngestReport
from cfb_upset.domain.coverage import CoverageReport, build_coverage
from cfb_upset.errors import CFBError
from cfb_upset.ids import new_ulid


@dataclass(frozen=True)
class IngestOptions:
    seasons: list[int]
    weeks: list[int] | None = None
    season_type: int = 2
    include_postseason: bool = False
    resume: bool = False
    batch_size: int = 10
    limit_games: int | None = None

    def season_types(self) -> list[int]:
        types = [self.season_type]
        if self.include_postseason and 3 not in types:
            types.append(3)
        return types


@dataclass
class IngestOutcome:
    report: IngestReport
    coverage: CoverageReport
    skipped_existing: int = 0
    odds_unavailable: int = 0
    failed_weeks: list[str] = field(default_factory=list)


class DataOrchestrator:
    """Enumerate, partition, aggregate, validate, store."""

    name = "Data-Orchestrator"

    def __init__(
        self,
        context: AgentContext,
        adapter: EspnAdapter,
        *,
        worker: HistoricalStatsWorker | None = None,
        worker_count: int | None = None,
    ) -> None:
        self.context = context
        self.adapter = adapter
        self.worker = worker or HistoricalStatsWorker(context, adapter)
        self.worker_count = max(1, worker_count or context.worker_count)
        self.last_coverage: CoverageReport | None = None

    async def run(self, options: IngestOptions) -> IngestOutcome:
        started_at = self.context.clock.now()
        self.context.emit(
            self.name,
            "enumerate",
            "ingest_started",
            {
                "seasons": options.seasons,
                "weeks": options.weeks,
                "season_types": options.season_types(),
                "resume": options.resume,
                "worker_count": self.worker_count,
            },
        )

        membership, failures = await self._membership(options)
        schedule, duplicates = await self._enumerate(options, membership, failures)
        selected = sorted(
            schedule.values(), key=lambda record: (record.kickoff_utc, record.game_id)
        )
        if options.limit_games is not None:
            selected = selected[: options.limit_games]

        fbs_team_ids = set().union(*membership.values()) if membership else set()
        if not selected:
            coverage = self._coverage(options)
            self.last_coverage = coverage
            finished_at = self.context.clock.now()
            report = IngestReport(
                report_id=new_ulid(self.context.clock),
                seasons=options.seasons,
                games_requested=0,
                games_stored=0,
                duplicates_removed=duplicates,
                quarantined=0,
                coverage=coverage.as_dict(),
                source="espn",
                started_at=started_at,
                finished_at=finished_at,
            )
            self.context.emit(
                self.name,
                "complete",
                "ingest_empty",
                {"failed_weeks": failures},
            )
            return IngestOutcome(report=report, coverage=coverage, failed_weeks=failures)

        weeks = await self._week_contexts(selected, options, failures)
        batches = self._build_batches(selected, options.batch_size)
        self.context.emit(
            self.name,
            "batch",
            "batches_planned",
            {
                "games": len(selected),
                "batches": len(batches),
                "duplicates_removed": duplicates,
                "weeks": len(weeks),
            },
        )

        outcomes = await self._run_batches(
            batches,
            schedule=schedule,
            weeks=weeks,
            fbs_team_ids=fbs_team_ids,
            resume=options.resume,
        )
        stored = sum(len(outcome.stored_ids) for outcome in outcomes)
        quarantined = sum(len(outcome.quarantined_ids) for outcome in outcomes)
        skipped = sum(len(outcome.skipped_ids) for outcome in outcomes)
        coverage = self._coverage(options)
        self.last_coverage = coverage
        finished_at = self.context.clock.now()
        report = IngestReport(
            report_id=new_ulid(self.context.clock),
            seasons=options.seasons,
            games_requested=len(selected),
            games_stored=stored,
            duplicates_removed=duplicates,
            quarantined=quarantined,
            coverage=coverage.as_dict(),
            source="espn",
            started_at=started_at,
            finished_at=finished_at,
        )
        self.context.emit(
            self.name,
            "complete",
            "ingest_completed",
            {
                "games_requested": len(selected),
                "games_stored": stored,
                "quarantined": quarantined,
                "skipped_existing": skipped,
                "duplicates_removed": duplicates,
                "leaked_admissible_fields": coverage.leaked_admissible_fields,
                "failed_weeks": failures,
            },
        )
        return IngestOutcome(
            report=report,
            coverage=coverage,
            skipped_existing=skipped,
            odds_unavailable=sum(outcome.odds_unavailable for outcome in outcomes),
            failed_weeks=failures,
        )

    # ------------------------------------------------------------------ phases
    async def _membership(
        self,
        options: IngestOptions,
    ) -> tuple[dict[int, set[str]], list[str]]:
        membership: dict[int, set[str]] = {}
        failures: list[str] = []
        for season in options.seasons:
            try:
                team_ids = await self.adapter.fetch_group_team_ids(
                    season=season,
                    season_type=options.season_type,
                    group_id=FBS_GROUP_ID,
                )
            except (CFBError, ValueError) as exc:
                failures.append(f"{season}:membership:{type(exc).__name__}: {exc}")
                continue
            membership[season] = set(team_ids)
            self.context.emit(
                self.name,
                "enumerate",
                "membership_loaded",
                {"season": season, "fbs_teams": len(team_ids)},
            )
        return membership, failures

    async def _enumerate(
        self,
        options: IngestOptions,
        membership: dict[int, set[str]],
        failures: list[str],
    ) -> tuple[dict[str, HistoricalGameRecord], int]:
        schedule: dict[str, HistoricalGameRecord] = {}
        duplicates = 0
        for season in options.seasons:
            fbs = membership.get(season)
            if not fbs:
                continue
            for season_type in options.season_types():
                weeks = await self._week_numbers(season, season_type, options, failures)
                for week in weeks:
                    self.context.check_budget("enumerate")
                    try:
                        records = await self.adapter.fetch_scoreboard(
                            season=season,
                            week=week,
                            season_type=season_type,
                            groups=FBS_GROUP_ID,
                            limit=500,
                        )
                    except (CFBError, ValueError) as exc:
                        failures.append(
                            f"{season}:{season_type}:{week}:{type(exc).__name__}: {exc}"
                        )
                        continue
                    kept = 0
                    for record in records:
                        if record.home.team_id not in fbs or record.away.team_id not in fbs:
                            continue
                        if record.status is not GameStatus.FINAL:
                            continue
                        if record.game_id in schedule:
                            duplicates += 1
                            continue
                        schedule[record.game_id] = record
                        kept += 1
                    self.context.emit(
                        self.name,
                        "enumerate",
                        "week_enumerated",
                        {
                            "season": season,
                            "season_type": season_type,
                            "week": week,
                            "events": len(records),
                            "kept": kept,
                        },
                    )
        return schedule, duplicates

    async def _week_numbers(
        self,
        season: int,
        season_type: int,
        options: IngestOptions,
        failures: list[str],
    ) -> list[int]:
        if options.weeks is not None:
            return sorted(set(options.weeks))
        try:
            return await self.adapter.fetch_week_numbers(season=season, season_type=season_type)
        except (CFBError, ValueError) as exc:
            failures.append(f"{season}:{season_type}:weeks:{type(exc).__name__}: {exc}")
            return []

    async def _week_contexts(
        self,
        selected: list[HistoricalGameRecord],
        options: IngestOptions,
        failures: list[str],
    ) -> dict[tuple[int, int, int | None], WeekContext]:
        grouped: dict[tuple[int, int, int | None], list[HistoricalGameRecord]] = {}
        for record in selected:
            grouped.setdefault((record.season, record.season_type, record.week), []).append(record)

        contexts: dict[tuple[int, int, int | None], WeekContext] = {}
        for (season, season_type, week), records in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                -1 if item[0][2] is None else item[0][2],
            ),
        ):
            earliest = min(record.kickoff_utc for record in records)
            rankings = await self._rankings(season, season_type, week, failures)
            contexts[(season, season_type, week)] = WeekContext(
                season=season,
                week=week,
                season_type=season_type,
                rankings=rankings,
                earliest_kickoff=earliest,
            )
        return contexts

    async def _rankings(
        self,
        season: int,
        season_type: int,
        week: int | None,
        failures: list[str],
    ) -> Rankings | None:
        if week is None or season_type != 2:
            return None
        try:
            return await self.adapter.fetch_core_rankings(
                season=season,
                week=week,
                season_type=season_type,
            )
        except (CFBError, ValueError) as exc:
            failures.append(f"{season}:{week}:rankings:{type(exc).__name__}: {exc}")
            return None

    def _build_batches(
        self,
        selected: list[HistoricalGameRecord],
        batch_size: int,
    ) -> list[GameIdBatch]:
        size = max(1, batch_size)
        batches: list[GameIdBatch] = []
        for index in range(0, len(selected), size):
            chunk = selected[index : index + size]
            seasons = {record.season for record in chunk}
            weeks = {record.week for record in chunk}
            batches.append(
                GameIdBatch(
                    batch_id=f"batch-{index // size:05d}",
                    game_ids=[record.game_id for record in chunk],
                    season=next(iter(seasons)) if len(seasons) == 1 else None,
                    week=next(iter(weeks)) if len(weeks) == 1 else None,
                )
            )
        return batches

    async def _run_batches(
        self,
        batches: list[GameIdBatch],
        *,
        schedule: dict[str, HistoricalGameRecord],
        weeks: dict[tuple[int, int, int | None], WeekContext],
        fbs_team_ids: set[str],
        resume: bool,
    ) -> list[BatchOutcome]:
        semaphore = asyncio.Semaphore(self.worker_count)

        async def run_one(batch: GameIdBatch) -> BatchOutcome:
            async with semaphore:
                self.context.check_budget("fetch")
                outcome = await self.worker.process_batch(
                    batch,
                    schedule=schedule,
                    weeks=weeks,
                    fbs_team_ids=fbs_team_ids,
                    resume=resume,
                )
                self.context.emit(
                    self.name,
                    "batch",
                    "batch_completed",
                    {
                        "batch_id": batch.batch_id,
                        "stored": len(outcome.stored_ids),
                        "quarantined": len(outcome.quarantined_ids),
                        "skipped": len(outcome.skipped_ids),
                        "odds_unavailable": outcome.odds_unavailable,
                    },
                )
                return outcome

        return list(await asyncio.gather(*(run_one(batch) for batch in batches)))

    def _coverage(self, options: IngestOptions) -> CoverageReport:
        return build_coverage(
            self.context.repositories.coverage.games(
                seasons=options.seasons,
                season_types=options.season_types(),
            ),
            self.context.repositories.coverage.fields(
                seasons=options.seasons,
                season_types=options.season_types(),
            ),
            seasons=options.seasons,
            season_types=options.season_types(),
            generated_at=self.context.clock.now(),
        )


__all__ = ["DataOrchestrator", "IngestOptions", "IngestOutcome"]
