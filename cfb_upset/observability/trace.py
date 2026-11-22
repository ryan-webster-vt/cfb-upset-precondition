"""In-memory run trace used by the Phase 0 walking skeleton.

P1 replaces the sink with JSONL + SQLite ``agent_events``, but the event shape
is already the contract the UI consumes.
"""

from __future__ import annotations

from typing import Any

from cfb_upset.contracts import AgentEvent
from cfb_upset.ids import Clock, SystemClock, new_ulid


class InMemoryTrace:
    """Collect ``AgentEvent`` objects in emission order."""

    def __init__(
        self,
        *,
        run_id: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.run_id = run_id or new_ulid(self.clock)
        self.events: list[AgentEvent] = []

    def emit(
        self,
        agent: str,
        phase: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            event_id=new_ulid(self.clock),
            run_id=self.run_id,
            agent=agent,
            phase=phase,
            event_type=event_type,
            payload=payload or {},
            ts=self.clock.now(),
        )
        self.events.append(event)
        return event
