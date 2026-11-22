"""Shared plumbing for the Phase 2 ingestion agents.

``AgentContext`` is the only object an agent needs: settings, typed
repositories, a trace, a budget, and a clock. Keeping it explicit makes the
orchestrator/worker split testable with a fixture transport and an in-memory
database, and keeps every agent event on the same ``run_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

from cfb_upset.config import Settings, get_settings
from cfb_upset.contracts import AgentEvent
from cfb_upset.ids import Clock, SystemClock
from cfb_upset.observability.budget import Budget
from cfb_upset.observability.trace import Trace
from cfb_upset.store.repositories import Repositories


@dataclass
class AgentContext:
    """Everything an agent may touch during one run."""

    settings: Settings
    repositories: Repositories
    trace: Trace
    budget: Budget
    clock: Clock
    worker_count: int = 2

    @classmethod
    def create(
        cls,
        repositories: Repositories,
        *,
        trace: Trace | None = None,
        budget: Budget | None = None,
        clock: Clock | None = None,
        settings: Settings | None = None,
        worker_count: int | None = None,
    ) -> AgentContext:
        resolved_settings = settings or get_settings()
        resolved_clock = clock or SystemClock()
        return cls(
            settings=resolved_settings,
            repositories=repositories,
            trace=trace or Trace(clock=resolved_clock),
            budget=budget or Budget(name="ingest"),
            clock=resolved_clock,
            worker_count=worker_count or resolved_settings.worker_count,
        )

    def emit(
        self,
        agent: str,
        phase: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> AgentEvent:
        return self.trace.emit(agent, phase, event_type, payload)

    def check_budget(self, phase: str) -> None:
        self.budget.check(phase)


__all__ = ["AgentContext"]
