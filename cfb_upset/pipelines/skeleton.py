"""Phase 0 walking skeleton.

fixture slate + fixture specs -> deterministic screen -> stub score -> ranked
alerts + an in-memory agent timeline. No network, no LLM, no database. Later
phases replace individual stages without changing the contracts or the UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from cfb_upset.contracts import PreconditionSpec, RunResult, RunStatus, SlateGame
from cfb_upset.domain.scoring import rank_alerts, score_matches
from cfb_upset.domain.screen import matched_game_ids, screen_slate
from cfb_upset.ids import Clock, SystemClock, new_ulid
from cfb_upset.observability.trace import InMemoryTrace


def run_walking_skeleton(
    games: list[SlateGame],
    specs: list[PreconditionSpec],
    contexts: Mapping[str, Mapping[str, object]],
    *,
    run_id: str | None = None,
    clock: Clock | None = None,
    base_rate: float = 0.20,
) -> RunResult:
    """Run the Phase 0 vertical slice and return a typed ``RunResult``."""

    clock = clock or SystemClock()
    trace = InMemoryTrace(run_id=run_id or new_ulid(clock), clock=clock)
    started_at = clock.now()
    slate_date = games[0].slate_date if games else date.today()

    trace.emit(
        "Monitor-Orchestrator",
        "start",
        "run_started",
        {"games": len(games), "specs": len(specs), "mode": "walking_skeleton"},
    )
    trace.emit(
        "Deterministic-Rule-Screen",
        "screen",
        "screen_started",
        {"games": len(games), "specs": len(specs)},
    )

    matches = screen_slate(games, specs, contexts)
    matched_ids = matched_game_ids(matches)
    trace.emit(
        "Deterministic-Rule-Screen",
        "screen",
        "screen_completed",
        {
            "matched_games": len(matched_ids),
            "evaluated_games": len(matches),
            "matched_game_ids": matched_ids,
        },
    )

    if not matched_ids:
        trace.emit(
            "Upset-Scorer",
            "score",
            "scoring_skipped",
            {"reason": "no_preconditions_matched"},
        )
        trace.emit(
            "Monitor-Orchestrator",
            "complete",
            "run_completed",
            {"status": RunStatus.NO_PRECONDITIONS_MATCHED.value},
        )
        return RunResult(
            run_id=trace.run_id,
            slate_date=slate_date,
            status=RunStatus.NO_PRECONDITIONS_MATCHED,
            alerts=[],
            matches=matches,
            events=list(trace.events),
            degraded=False,
            reason="No upset alerts for this slate",
            started_at=started_at,
            finished_at=clock.now(),
        )

    trace.emit(
        "Monitor-Orchestrator",
        "confirm",
        "confirmation_skipped",
        {
            "reason": "Phase 0 fixture skeleton; cited web confirmation lands in P7",
            "candidates": len(matched_ids),
        },
    )
    trace.emit(
        "Upset-Scorer",
        "score",
        "scoring_started",
        {"candidates": len(matched_ids), "backend": "calibrated_rules"},
    )

    scores = score_matches(matches, specs, base_rate=base_rate)
    alerts = rank_alerts(matches, games, specs, scores)
    trace.emit(
        "Upset-Scorer",
        "score",
        "alerts_ranked",
        {
            "alerts": len(alerts),
            "backend": "calibrated_rules",
            "model_version": next(iter(scores.values())).model_version if scores else None,
        },
    )
    trace.emit(
        "Monitor-Orchestrator",
        "complete",
        "run_completed",
        {"status": RunStatus.COMPLETED.value, "alerts": len(alerts)},
    )

    return RunResult(
        run_id=trace.run_id,
        slate_date=slate_date,
        status=RunStatus.COMPLETED,
        alerts=alerts,
        matches=matches,
        events=list(trace.events),
        degraded=False,
        reason=None,
        started_at=started_at,
        finished_at=clock.now(),
    )
