"""Parallelism evidence for R6: two workers must beat one worker by >1.5x.

The test uses a synthetic transport with a fixed per-request delay, so the
measurement is deterministic and never touches the network. Each game costs two
requests (summary + odds); forty games are split into four batches of ten.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.adapters.transport import TransportResponse
from cfb_upset.agents import AgentContext, DataOrchestrator, IngestOptions
from cfb_upset.ids import FrozenClock
from cfb_upset.observability.budget import Budget
from cfb_upset.observability.trace import InMemoryTrace
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
KICKOFF = "2024-09-28T23:30Z"
GAMES = 40
REQUEST_DELAY_S = 0.01

pytestmark = pytest.mark.slow


class SlowTransport:
    """Serves synthetic ESPN payloads after a fixed delay per request."""

    def __init__(self, game_ids: list[str], delay_s: float = REQUEST_DELAY_S) -> None:
        self.game_ids = game_ids
        self.delay_s = delay_s
        self.calls: list[str] = []

    def to_game(self, game_id: str) -> tuple[str, str]:
        index = self.game_ids.index(game_id)
        return str(100 + index), str(200 + index)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> TransportResponse:
        await asyncio.sleep(self.delay_s)
        full = f"{url}?{urlencode(params)}" if params else url
        self.calls.append(full)
        if "/groups/80/teams" in url:
            return _response(
                {
                    "items": [
                        {"$ref": f"https://core/teams/{team}"}
                        for team_id in self.game_ids
                        for team in self.to_game(team_id)
                    ]
                }
            )
        if "/types/2/weeks" in url:
            return _response({"items": [{"$ref": "https://core/weeks/1"}]})
        if "/scoreboard" in url:
            return _response({"events": [self._event(game_id) for game_id in self.game_ids]})
        if "/weeks/1/rankings?limit=50" in full:
            return _response({"items": [{"$ref": "https://core/weeks/1/rankings/1"}]})
        if "/weeks/1/rankings/1" in url:
            return _response({"shortName": "AP Poll", "date": "2024-09-22T07:00Z", "ranks": []})
        if "/summary?event=" in full:
            game_id = full.split("event=", 1)[1].split("&", 1)[0]
            return _response(self._summary(game_id))
        if "/odds" in url:
            return _response({"items": []})
        return _response({"error": "not found", "url": full}, status_code=404)

    def _event(self, game_id: str) -> dict[str, Any]:
        home, away = self.to_game(game_id)
        return {
            "id": game_id,
            "date": KICKOFF,
            "season": {"year": 2024, "type": 2},
            "week": {"number": 1},
            "competitions": [self._competition(game_id, home, away)],
        }

    def _summary(self, game_id: str) -> dict[str, Any]:
        home, away = self.to_game(game_id)
        return {
            "header": {
                "id": game_id,
                "season": {"year": 2024, "type": 2},
                "week": 1,
                "competitions": [self._competition(game_id, home, away)],
            },
            "gameInfo": {"venue": {"id": "v1", "fullName": "Test Stadium"}},
            "boxscore": {"teams": []},
        }

    @staticmethod
    def _competition(game_id: str, home: str, away: str) -> dict[str, Any]:
        return {
            "id": game_id,
            "date": KICKOFF,
            "neutralSite": False,
            "conferenceCompetition": True,
            "status": {"type": {"name": "STATUS_FINAL", "completed": True, "state": "post"}},
            "competitors": [
                {
                    "homeAway": "home",
                    "id": home,
                    "winner": True,
                    "score": "31",
                    "team": {"id": home, "location": f"Home {home}", "abbreviation": "HOM"},
                    "curatedRank": {"current": 99},
                },
                {
                    "homeAway": "away",
                    "id": away,
                    "winner": False,
                    "score": "17",
                    "team": {"id": away, "location": f"Away {away}", "abbreviation": "AWY"},
                    "curatedRank": {"current": 99},
                },
            ],
            "venue": {"id": "v1", "fullName": "Test Stadium"},
        }


def _response(payload: dict[str, Any], *, status_code: int = 200) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        url="",
    )


async def timed_run(tmp_path: Path, *, worker_count: int) -> tuple[float, Repositories]:
    database = Database(tmp_path / f"cfb-{worker_count}.db")
    database.initialize()
    repositories = Repositories(database)
    clock = FrozenClock(NOW)
    context = AgentContext.create(
        repositories,
        trace=InMemoryTrace(clock=clock),
        budget=Budget(name="timing"),
        clock=clock,
        worker_count=worker_count,
    )
    game_ids = [f"9000{i:04d}" for i in range(GAMES)]
    adapter = EspnAdapter(SlowTransport(game_ids), clock=clock)
    orchestrator = DataOrchestrator(context, adapter, worker_count=worker_count)
    started = time.perf_counter()
    outcome = await orchestrator.run(IngestOptions(seasons=[2024], weeks=[1], batch_size=10))
    elapsed = time.perf_counter() - started
    assert outcome.report.games_stored == GAMES
    return elapsed, repositories


async def test_two_workers_beat_one_worker_by_1_5x(tmp_path: Path) -> None:
    one_worker, repositories_one = await timed_run(tmp_path, worker_count=1)
    two_workers, repositories_two = await timed_run(tmp_path, worker_count=2)
    assert repositories_one.games.count() == GAMES
    assert repositories_two.games.count() == GAMES
    print(
        f"one_worker={one_worker:.3f}s two_workers={two_workers:.3f}s "
        f"ratio={two_workers / one_worker:.2f}"
    )
    assert (
        two_workers < 1.5 * one_worker
    ), f"one worker {one_worker:.3f}s vs two workers {two_workers:.3f}s"
