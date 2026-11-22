"""Tracing sinks and run budgets: required fields, persistence, and exhaustion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.errors import BudgetExhausted
from cfb_upset.ids import FrozenClock
from cfb_upset.observability.budget import Budget
from cfb_upset.observability.trace import (
    InMemoryTrace,
    JsonlTraceSink,
    SqliteEventSink,
    Trace,
)
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def test_in_memory_trace_emits_required_fields() -> None:
    trace = InMemoryTrace(run_id="run-1", clock=FrozenClock(NOW))
    event = trace.emit("Upset-Scorer", "score", "scored", {"alerts": 2})
    assert event.run_id == "run-1"
    assert event.agent == "Upset-Scorer"
    assert event.phase == "score"
    assert event.event_type == "scored"
    assert event.ts == NOW
    assert event.payload == {"alerts": 2}
    assert trace.events == [event]


def test_jsonl_sink_writes_canonical_one_event_per_line(tmp_path: Path) -> None:
    path = tmp_path / "run-1.jsonl"
    trace = Trace(run_id="run-1", clock=FrozenClock(NOW), sinks=[JsonlTraceSink(path)])
    trace.emit("Data-Orchestrator", "ingest", "started", {"season": 2025})
    trace.emit("Data-Orchestrator", "ingest", "finished", {"games": 3})
    trace.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert list(payloads[0]) == sorted(payloads[0])
    for item in payloads:
        assert {"run_id", "agent", "phase", "event_type", "ts"} <= set(item)
        assert item["ts"] == "2026-11-22T12:00:00Z"

    sink = JsonlTraceSink(path)
    assert [event.event_type for event in sink.read()] == ["started", "finished"]


def test_jsonl_sink_treats_a_directory_as_a_run_file(tmp_path: Path) -> None:
    sink = JsonlTraceSink(tmp_path / "traces", run_id="run-9")
    assert sink.path.name == "run-run-9.jsonl"
    assert sink.path.parent.is_dir()


def test_jsonl_sink_read_of_missing_file_is_empty(tmp_path: Path) -> None:
    assert JsonlTraceSink(tmp_path / "nothing.jsonl").read() == []


def test_sqlite_sink_persists_events_for_a_run(tmp_path: Path) -> None:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    repositories = Repositories(database)
    trace = Trace(
        run_id="run-1",
        clock=FrozenClock(NOW),
        sinks=[SqliteEventSink(repositories)],
    )
    trace.emit("Upset-Scorer", "score", "scored", {"alerts": 1})
    trace.close()

    stored = repositories.events.list_for_run("run-1")
    assert len(stored) == 1
    assert stored[0].agent == "Upset-Scorer"
    assert stored[0].payload == {"alerts": 1}


def test_trace_fans_out_to_all_sinks_and_closes(tmp_path: Path) -> None:
    class CountingSink:
        def __init__(self) -> None:
            self.events = []
            self.closed = False

        def write(self, event) -> None:
            self.events.append(event)

        def close(self) -> None:
            self.closed = True

    sink = CountingSink()
    jsonl = JsonlTraceSink(tmp_path / "trace.jsonl")
    with Trace(run_id="run-2", clock=FrozenClock(NOW), sinks=[sink, jsonl]) as trace:
        trace.emit("A", "p", "e")
    assert len(sink.events) == 1
    assert sink.closed is True
    assert len(jsonl.read()) == 1


def test_budget_deadline_and_counters() -> None:
    clock = [0.0]
    budget = Budget(
        name="run",
        deadline_s=10.0,
        max_tokens=5,
        max_pages=1,
        max_fetches=1,
        monotonic_fn=lambda: clock[0],
    )
    budget.start()
    assert budget.remaining_s == pytest.approx(10.0)
    budget.check("llm")
    clock[0] = 4.0
    assert budget.elapsed_s == pytest.approx(4.0)
    assert budget.remaining_s == pytest.approx(6.0)

    budget.consume_tokens(2, phase="llm")
    budget.consume_page(phase="research")
    budget.consume_fetch(phase="research")
    assert budget.snapshot()["tokens_used"] == 2
    assert budget.snapshot()["pages_used"] == 1
    assert budget.snapshot()["fetches_used"] == 1

    clock[0] = 10.0
    with pytest.raises(BudgetExhausted, match="deadline"):
        budget.check("llm")
    assert budget.events[-1]["event"] == "budget_exhausted"


def test_budget_raises_on_each_exceeded_counter() -> None:
    tokens = Budget(max_tokens=1)
    with pytest.raises(BudgetExhausted, match="token budget"):
        tokens.consume_tokens(2)

    pages = Budget(max_pages=0)
    with pytest.raises(BudgetExhausted, match="page budget"):
        pages.consume_page()

    fetches = Budget(max_fetches=0)
    with pytest.raises(BudgetExhausted, match="fetch budget"):
        fetches.consume_fetch()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deadline_s": -1.0},
        {"max_tokens": -1},
        {"max_pages": -1},
        {"max_fetches": -1},
    ],
)
def test_budget_rejects_negative_limits(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Budget(**kwargs)


def test_budget_rejects_negative_consumption() -> None:
    with pytest.raises(ValueError):
        Budget().consume_tokens(-1)


def test_budget_snapshot_has_stable_keys() -> None:
    snapshot = Budget(name="phase", deadline_s=30, max_tokens=100).snapshot()
    assert snapshot["name"] == "phase"
    assert snapshot["deadline_s"] == 30
    assert snapshot["remaining_s"] is not None
    assert set(snapshot) == {
        "name",
        "deadline_s",
        "elapsed_s",
        "remaining_s",
        "max_tokens",
        "tokens_used",
        "max_pages",
        "pages_used",
        "max_fetches",
        "fetches_used",
    }
