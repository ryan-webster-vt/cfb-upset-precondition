"""Deadlines and counters for a single run/phase.

Budgets are deliberately explicit: an agent calls ``check`` before spending and
``consume_*`` after. Exhaustion raises ``BudgetExhausted`` so the orchestrator
can emit a ``degraded`` result instead of hanging or overspending.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cfb_upset.errors import BudgetExhausted

MonotonicFn = Callable[[], float]


@dataclass
class Budget:
    name: str = "run"
    deadline_s: float | None = None
    max_tokens: int | None = None
    max_pages: int | None = None
    max_fetches: int | None = None
    tokens_used: int = 0
    pages_used: int = 0
    fetches_used: int = 0
    started_at: float = field(default_factory=time.monotonic)
    monotonic_fn: MonotonicFn = time.monotonic
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.deadline_s is not None and self.deadline_s < 0:
            raise ValueError("deadline_s must be non-negative")
        for value in (self.max_tokens, self.max_pages, self.max_fetches):
            if value is not None and value < 0:
                raise ValueError("budget limits must be non-negative")

    def start(self) -> Budget:
        self.started_at = self.monotonic_fn()
        return self

    @property
    def elapsed_s(self) -> float:
        return max(0.0, self.monotonic_fn() - self.started_at)

    @property
    def remaining_s(self) -> float | None:
        if self.deadline_s is None:
            return None
        return max(0.0, self.deadline_s - self.elapsed_s)

    def check(self, phase: str = "run") -> None:
        if self.deadline_s is not None and self.elapsed_s >= self.deadline_s:
            self._exhaust(f"{self.name}:{phase} deadline {self.deadline_s:.1f}s exceeded")

    def consume_tokens(self, count: int, *, phase: str = "run") -> None:
        if count < 0:
            raise ValueError("token count must be non-negative")
        self.tokens_used += count
        if self.max_tokens is not None and self.tokens_used > self.max_tokens:
            self._exhaust(
                f"{self.name}:{phase} token budget exceeded "
                f"({self.tokens_used}/{self.max_tokens})"
            )

    def consume_page(self, *, phase: str = "run") -> None:
        self.pages_used += 1
        if self.max_pages is not None and self.pages_used > self.max_pages:
            self._exhaust(
                f"{self.name}:{phase} page budget exceeded " f"({self.pages_used}/{self.max_pages})"
            )

    def consume_fetch(self, *, phase: str = "run") -> None:
        self.fetches_used += 1
        if self.max_fetches is not None and self.fetches_used > self.max_fetches:
            self._exhaust(
                f"{self.name}:{phase} fetch budget exceeded "
                f"({self.fetches_used}/{self.max_fetches})"
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "deadline_s": self.deadline_s,
            "elapsed_s": round(self.elapsed_s, 3),
            "remaining_s": None if self.remaining_s is None else round(self.remaining_s, 3),
            "max_tokens": self.max_tokens,
            "tokens_used": self.tokens_used,
            "max_pages": self.max_pages,
            "pages_used": self.pages_used,
            "max_fetches": self.max_fetches,
            "fetches_used": self.fetches_used,
        }

    def _exhaust(self, message: str) -> None:
        self.events.append({"event": "budget_exhausted", "message": message})
        raise BudgetExhausted(message)


__all__ = ["Budget"]
