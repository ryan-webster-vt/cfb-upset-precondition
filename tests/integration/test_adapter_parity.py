"""Fixture-transport parity: replaying a captured payload equals direct parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cfb_upset.adapters.cfbd import CfbdAdapter
from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.ids import FrozenClock
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import Repositories

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


async def test_espn_scoreboard_fetch_and_parse_are_byte_identical() -> None:
    payload = json.loads((FIXTURES / "espn" / "scoreboard_20251115.json").read_text())
    direct = EspnAdapter(FixtureTransport(), clock=FrozenClock(NOW)).parse_scoreboard(
        payload, fetched_at=NOW
    )
    transport = FixtureTransport().add_json_file(
        "/scoreboard", FIXTURES / "espn" / "scoreboard_20251115.json"
    )
    fetched = await EspnAdapter(transport, clock=FrozenClock(NOW)).fetch_scoreboard(
        dates="20251115"
    )
    assert [record.model_dump() for record in fetched] == [record.model_dump() for record in direct]


async def test_espn_summary_fetch_and_parse_are_byte_identical() -> None:
    payload = json.loads((FIXTURES / "espn" / "summary_401628543.json").read_text())
    direct = EspnAdapter(FixtureTransport(), clock=FrozenClock(NOW)).parse_summary(
        payload, fetched_at=NOW
    )
    transport = FixtureTransport().add_json_file(
        "/summary", FIXTURES / "espn" / "summary_401628543.json"
    )
    fetched = await EspnAdapter(transport, clock=FrozenClock(NOW)).fetch_summary("401628543")
    assert fetched.model_dump() == direct.model_dump()


async def test_cfbd_lines_fetch_and_parse_are_identical() -> None:
    path = FIXTURES / "cfbd" / "lines_2025_w1.json"
    payload = json.loads(path.read_text())
    direct = CfbdAdapter.parse_lines(payload)
    transport = FixtureTransport().add_json_file("/lines", path)
    fetched = await CfbdAdapter(transport, line_providers=["DraftKings"]).fetch_lines(
        season=2025, week=1
    )
    assert fetched == direct


async def test_ingested_fixture_round_trips_through_sqlite(tmp_path: Path) -> None:
    transport = FixtureTransport().add_json_file(
        "/scoreboard", FIXTURES / "espn" / "scoreboard_20251115.json"
    )
    records = await EspnAdapter(transport, clock=FrozenClock(NOW)).fetch_scoreboard(
        dates="20251115"
    )
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    repositories = Repositories(database)
    for record in records:
        repositories.games.upsert(record)

    for record in records:
        stored = repositories.games.get(record.game_id)
        assert stored is not None
        assert stored.home_team_id == record.home.team_id
        assert stored.home_score == record.home_score
        assert repositories.game_fields.get(record.game_id)["home"].source == "espn"
