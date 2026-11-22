"""Run tracing: in-memory events, JSONL files, and the ``agent_events`` table.

The Phase 0 ``InMemoryTrace`` API is preserved. ``Trace`` fans the same event
out to any sinks, so the UI, the JSONL artifact, and SQLite always agree on the
required fields ``run_id``, ``agent``, ``phase``, ``event_type``, and ``ts``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from cfb_upset.config import get_settings
from cfb_upset.contracts import AgentEvent
from cfb_upset.ids import Clock, SystemClock, canonical_json, new_ulid


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


class TraceSink(Protocol):
    def write(self, event: AgentEvent) -> None: ...

    def close(self) -> None: ...


class JsonlTraceSink:
    """Append-only JSONL sink: one canonical event object per line."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        raw = Path(path).expanduser() if path is not None else Path(get_settings().trace_path)
        if raw.suffix == ".jsonl" or raw.is_file():
            self.path = raw
        else:
            self.path = raw / f"run-{run_id or 'unknown'}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AgentEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(event.model_dump(mode="json")))
            handle.write("\n")

    def close(self) -> None:
        return None

    def read(self) -> list[AgentEvent]:
        if not self.path.exists():
            return []
        events: list[AgentEvent] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(AgentEvent.model_validate(json.loads(line)))
        return events


class SqliteEventSink:
    """Write every event to ``agent_events`` through the typed repository."""

    def __init__(self, repositories: Any, *, initialize: bool = False) -> None:
        self.repositories = repositories
        if initialize:
            self.repositories.database.initialize()

    def write(self, event: AgentEvent) -> None:
        self.repositories.events.append(event)

    def close(self) -> None:
        return None


class Trace(InMemoryTrace):
    """Fan an in-memory trace out to durable sinks."""

    def __init__(
        self,
        *,
        run_id: str | None = None,
        clock: Clock | None = None,
        sinks: Iterable[TraceSink] | None = None,
    ) -> None:
        super().__init__(run_id=run_id, clock=clock)
        self.sinks = list(sinks or [])

    def emit(
        self,
        agent: str,
        phase: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = super().emit(agent, phase, event_type, payload)
        for sink in self.sinks:
            sink.write(event)
        return event

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()

    def __enter__(self) -> Trace:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


__all__ = [
    "InMemoryTrace",
    "JsonlTraceSink",
    "SqliteEventSink",
    "Trace",
    "TraceSink",
]
