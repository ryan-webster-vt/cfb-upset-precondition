"""Historical-Stats Worker: one game -> one validated ``HistoricalGameRecord``.

The worker owns the per-game fetch path (summary + core odds + weekly poll) and
never decides *which* games exist. That is the orchestrator's job. Failures are
isolated per game: a 500 summary or an unparseable payload quarantines only that
game and the batch continues (P2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import ValidationError

from cfb_upset.adapters.espn import EspnAdapter, Rankings
from cfb_upset.agents.base import AgentContext
from cfb_upset.contracts import (
    GameIdBatch,
    GameStatus,
    HistoricalGameRecord,
    Provenance,
    QuarantineRecord,
)
from cfb_upset.domain.leakage import LeakageError, policy_for
from cfb_upset.errors import CFBError, ContractError

# Fields every stored game must be able to prove. Optional context (venue,
# odds, weather) may be absent; absence is measured by the coverage report.
REQUIRED_FIELDS = (
    "game_id",
    "season",
    "kickoff_utc",
    "home",
    "away",
    "neutral_site",
    "conference_game",
    "status",
    "home_score",
    "away_score",
    "winner_team_id",
)


@dataclass(frozen=True)
class WeekContext:
    """Per-week state shared by every game in that week."""

    season: int
    week: int | None
    season_type: int = 2
    rankings: Rankings | None = None
    earliest_kickoff: datetime | None = None


@dataclass
class BatchOutcome:
    batch_id: str
    stored_ids: list[str] = field(default_factory=list)
    quarantined_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    odds_unavailable: int = 0
    rankings_applied: int = 0


class HistoricalStatsWorker:
    """Fetch, validate, and persist one game at a time."""

    name = "Historical-Stats-Worker"

    def __init__(self, context: AgentContext, adapter: EspnAdapter) -> None:
        self.context = context
        self.adapter = adapter
        self.repositories = context.repositories

    async def process_batch(
        self,
        batch: GameIdBatch,
        *,
        schedule: dict[str, HistoricalGameRecord],
        weeks: dict[tuple[int, int, int | None], WeekContext],
        fbs_team_ids: set[str],
        resume: bool = False,
    ) -> BatchOutcome:
        outcome = BatchOutcome(batch_id=batch.batch_id)
        for game_id in batch.game_ids:
            if resume and self.repositories.games.get(game_id) is not None:
                outcome.skipped_ids.append(game_id)
                continue
            scheduled = schedule[game_id]
            week_context = weeks.get((scheduled.season, scheduled.season_type, scheduled.week))
            try:
                record, unavailable_odds, ranked = await self._fetch_and_merge(
                    scheduled,
                    week_context=week_context,
                )
                _validate_record(record, fbs_team_ids=fbs_team_ids)
                self.repositories.games.upsert(record)
            except (CFBError, ValidationError, ValueError) as exc:
                self._quarantine(game_id, scheduled, exc)
                outcome.quarantined_ids.append(game_id)
                continue
            outcome.stored_ids.append(game_id)
            outcome.odds_unavailable += int(unavailable_odds)
            outcome.rankings_applied += int(ranked)
        return outcome

    async def _fetch_and_merge(
        self,
        scheduled: HistoricalGameRecord,
        *,
        week_context: WeekContext | None,
    ) -> tuple[HistoricalGameRecord, bool, bool]:
        game_id = scheduled.game_id
        summary = await self.adapter.fetch_summary(game_id)
        kickoff = summary.kickoff_utc
        odds = None
        odds_unavailable = False
        try:
            items = await self.adapter.fetch_odds(game_id)
            odds = self.adapter.parse_odds(
                items,
                home_team_id=summary.home.team_id,
                away_team_id=summary.away.team_id,
                kickoff=kickoff,
                fetched_at=self.context.clock.now(),
            )
            odds_unavailable = odds is None
        except (CFBError, ValueError):
            # A missing market is a coverage gap, not a corrupt game.
            odds_unavailable = True

        record = summary.model_copy(
            update={
                "week": summary.week if summary.week is not None else scheduled.week,
                "season": summary.season or scheduled.season,
                "neutral_site": summary.neutral_site or scheduled.neutral_site,
                "conference_game": summary.conference_game or scheduled.conference_game,
                "odds": odds,
                "is_fbs_vs_fbs": True,
                "source": "espn",
                "fetched_at": self.context.clock.now(),
            }
        )
        provenance = dict(summary.field_provenance)
        provenance.update(
            {
                key: value
                for key, value in scheduled.field_provenance.items()
                if key not in provenance and key != "odds"
            }
        )
        if odds is not None:
            provenance["odds"] = Provenance(
                source="espn",
                source_url=f"{self.adapter.core_base_url}/events/{game_id}",
                fetched_at=self.context.clock.now(),
                known_at=odds.known_at,
            )
        ranked = _apply_rankings(record, provenance, week_context, kickoff=kickoff)
        return record.model_copy(update={"field_provenance": provenance}), odds_unavailable, ranked

    def _quarantine(
        self,
        game_id: str,
        scheduled: HistoricalGameRecord,
        exc: Exception,
    ) -> None:
        message = f"{type(exc).__name__}: {exc}"
        self.repositories.quarantine.add(
            QuarantineRecord(
                record_id=f"{scheduled.season}:{scheduled.week}:{game_id}",
                payload={
                    "game_id": game_id,
                    "season": scheduled.season,
                    "week": scheduled.week,
                    "stage": "historical_stats_worker",
                    "kickoff_utc": scheduled.kickoff_utc.isoformat(),
                },
                errors=[message],
                source="espn",
                created_at=self.context.clock.now(),
            )
        )
        self.context.emit(
            self.name,
            "fetch",
            "game_quarantined",
            {"game_id": game_id, "error": message},
        )


def _apply_rankings(
    record: HistoricalGameRecord,
    provenance: dict[str, Provenance],
    week_context: WeekContext | None,
    *,
    kickoff: datetime,
) -> bool:
    """Replace the (unreliable) historical ``curatedRank`` with the weekly poll."""

    if week_context is None or week_context.rankings is None:
        return False
    rankings = week_context.rankings
    home_rank = rankings.ranks.get(record.home.team_id)
    away_rank = rankings.ranks.get(record.away.team_id)
    record.home = record.home.model_copy(update={"rank": home_rank})
    record.away = record.away.model_copy(update={"rank": away_rank})
    known_at = _rank_known_at(week_context, kickoff=kickoff)
    source_url = f"espn-core://rankings/{rankings.season}/week/{rankings.week}"
    for field_name in ("home", "away"):
        provenance[field_name] = Provenance(
            source="espn_rankings",
            source_url=source_url,
            fetched_at=rankings.published_at or known_at,
            known_at=known_at,
        )
    return True


def _rank_known_at(week_context: WeekContext, *, kickoff: datetime) -> datetime:
    published = week_context.rankings.published_at if week_context.rankings else None
    if published is not None and published < kickoff:
        return published
    if week_context.earliest_kickoff is not None:
        return week_context.earliest_kickoff - timedelta(hours=1)
    return kickoff - timedelta(days=7)


def _validate_record(record: HistoricalGameRecord, *, fbs_team_ids: set[str]) -> None:
    """Fail closed: provenance completeness, FBS membership, and no leakage."""

    errors: list[str] = []
    missing = [name for name in REQUIRED_FIELDS if name not in record.field_provenance]
    if missing:
        errors.append(f"missing provenance for {', '.join(missing)}")
    for team_id, label in ((record.home.team_id, "home"), (record.away.team_id, "away")):
        if team_id not in fbs_team_ids:
            errors.append(f"{label} team {team_id} is not in the season FBS group")
    if record.status is GameStatus.FINAL:
        if record.home_score is None or record.away_score is None:
            errors.append("final game has no score (label would be undefined)")

    for field_name, provenance in record.field_provenance.items():
        try:
            policy = policy_for(field_name)
        except LeakageError as exc:
            errors.append(str(exc))
            continue
        if provenance.known_at.tzinfo is None:
            errors.append(f"{field_name} has a naive known_at")
        if policy.admissible and provenance.known_at >= record.kickoff_utc:
            errors.append(
                f"{field_name} leaked: known_at={provenance.known_at.isoformat()} "
                f">= kickoff={record.kickoff_utc.isoformat()}"
            )
    if errors:
        raise ContractError("; ".join(errors))


__all__ = [
    "BatchOutcome",
    "HistoricalStatsWorker",
    "REQUIRED_FIELDS",
    "WeekContext",
]
