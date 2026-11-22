"""Offline integration tests for Pipeline 1 (fixture-backed, no network).

Fixtures are a recorded 2024 week 5 slate: FBS membership, week list, five
FBS-vs-FBS final games, their summaries and core odds, and the week-5 AP poll.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.agents import AgentContext, DataOrchestrator, IngestOptions
from cfb_upset.domain.coverage import build_coverage
from cfb_upset.domain.leakage import policy_for
from cfb_upset.ids import FrozenClock
from cfb_upset.observability.budget import Budget
from cfb_upset.observability.trace import InMemoryTrace
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import CoverageFieldRow, CoverageGameRow, Repositories

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "espn" / "p2"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
GAME_IDS = (
    "401645331",
    "401634767",
    "401628501",
    "401628378",
    "401628374",
)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def build_transport(
    *,
    failing: set[str] | None = None,
    scoreboard_routes: dict[int, dict] | None = None,
) -> FixtureTransport:
    failing = failing or set()
    transport = FixtureTransport()
    transport.add_json_file("/groups/80/teams", FIXTURES / "membership_2024_g80.json")
    transport.add_json_file("/types/2/weeks", FIXTURES / "weeks_2024_type2.json")
    if scoreboard_routes:
        for week, payload in sorted(scoreboard_routes.items()):
            transport.add(f"week={week}", payload)
    else:
        transport.add_json_file("/scoreboard", FIXTURES / "week_2024_w05_scoreboard.json")
    # The listing route must be registered before the poll route.
    transport.add_json_file("/weeks/5/rankings?limit=50", FIXTURES / "rankings_2024_w05_list.json")
    transport.add_json_file("/weeks/5/rankings/1", FIXTURES / "rankings_2024_w05_ap.json")
    for game_id in GAME_IDS:
        if game_id in failing:
            transport.add(
                f"/summary?event={game_id}",
                {"error": "upstream failure"},
                status_code=500,
            )
        else:
            transport.add_json_file(
                f"/summary?event={game_id}", FIXTURES / f"summary_{game_id}.json"
            )
        transport.add_json_file(
            f"/events/{game_id}/competitions/{game_id}/odds",
            FIXTURES / f"odds_{game_id}.json",
        )
    return transport


def make_context(tmp_path: Path, *, worker_count: int = 2) -> tuple[AgentContext, Repositories]:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    repositories = Repositories(database)
    clock = FrozenClock(NOW)
    context = AgentContext.create(
        repositories,
        trace=InMemoryTrace(clock=clock),
        budget=Budget(name="test"),
        clock=clock,
        worker_count=worker_count,
    )
    return context, repositories


async def run_fixture_week(
    tmp_path: Path,
    *,
    transport: FixtureTransport,
    resume: bool = False,
    weeks: list[int] | None = None,
    worker_count: int = 2,
    report_dir: Path | None = None,
) -> tuple[object, Repositories, InMemoryTrace]:
    context, repositories = make_context(tmp_path, worker_count=worker_count)
    adapter = EspnAdapter(transport, clock=context.clock)
    orchestrator = DataOrchestrator(context, adapter, worker_count=worker_count)
    outcome = await orchestrator.run(
        IngestOptions(
            seasons=[2024],
            weeks=weeks or [5],
            resume=resume,
            batch_size=2,
        )
    )
    return outcome, repositories, context.trace


def test_fixture_week_stores_exact_count_and_provenance(tmp_path: Path) -> None:
    transport = build_transport()
    outcome, repositories, _trace = run_fixture_week_sync(tmp_path, transport)

    report = outcome.report
    assert report.games_requested == 5
    assert report.games_stored == 5
    assert report.quarantined == 0
    assert report.duplicates_removed == 0
    assert repositories.games.count() == 5
    assert repositories.quarantine.count() == 0
    # 16 provenance fields per game: 15 from the summary plus odds.
    assert repositories.game_fields.count() == 80
    assert repositories.games.list(season=2024, week=5, fbs_only=True)

    for game_id in GAME_IDS:
        stored = repositories.games.get(game_id)
        assert stored is not None and stored.season == 2024
        fields = repositories.game_fields.get(game_id)
        required = {
            "game_id",
            "season",
            "kickoff_utc",
            "home",
            "away",
            "venue",
            "status",
            "home_score",
            "away_score",
            "winner_team_id",
            "team_stats",
        }
        assert required <= set(fields)
        # Box scores are stored, explicitly post-game, and never admissible.
        for name in ("home_score", "away_score", "winner_team_id", "team_stats"):
            assert fields[name].source == "espn_postgame"
            assert fields[name].known_at_utc == stored.kickoff_utc
            assert policy_for(name).admissible is False
        # Every admissible field is strictly before kickoff.
        for name, field in fields.items():
            if policy_for(name).admissible:
                assert field.known_at_utc < stored.kickoff_utc, name


def test_fixture_week_coverage_report(tmp_path: Path) -> None:
    transport = build_transport()
    outcome, repositories, _trace = run_fixture_week_sync(tmp_path, transport)
    coverage = outcome.coverage

    assert coverage.total_games == 5
    assert coverage.games_by_season == {2024: 5}
    assert coverage.leaked_admissible_fields == 0
    assert coverage.ok
    assert coverage.label_only_fields == [
        "away_score",
        "home_score",
        "team_stats",
        "winner_team_id",
    ]
    assert coverage.overall["venue"].pct == pytest.approx(100.0)
    assert "weather" in coverage.unsupported_fields
    assert sum(coverage.favorite_sources.values()) == 5

    markdown = coverage.render_markdown()
    assert "Field coverage by season" in markdown
    assert "Team coverage" in markdown
    assert "Leakage check" in markdown


def test_fault_isolates_one_bad_summary(tmp_path: Path) -> None:
    transport = build_transport(failing={"401628378"})
    outcome, repositories, _trace = run_fixture_week_sync(tmp_path, transport)

    assert outcome.report.games_stored == 4
    assert outcome.report.quarantined == 1
    assert repositories.games.count() == 4
    assert repositories.quarantine.count() == 1
    quarantined = repositories.quarantine.list()
    assert quarantined[0].payload["game_id"] == "401628378"
    assert "500" in quarantined[0].errors[0]


def test_resume_skips_stored_games_without_duplicate_fetches(tmp_path: Path) -> None:
    transport = build_transport()
    outcome, repositories, _trace = run_fixture_week_sync(tmp_path, transport)
    assert outcome.report.games_stored == 5

    transport.calls.clear()
    second, repositories, _trace = run_fixture_week_sync(tmp_path, transport, resume=True)
    assert second.report.games_stored == 0
    assert second.skipped_existing == 5
    assert repositories.games.count() == 5
    fetches = [call.url for call in transport.calls]
    assert not [url for url in fetches if "/summary?event=" in url]
    assert not [url for url in fetches if "/odds" in url]


def test_idempotent_rerun_without_resume_does_not_duplicate_rows(tmp_path: Path) -> None:
    transport = build_transport()
    run_fixture_week_sync(tmp_path, transport)
    second, repositories, _trace = run_fixture_week_sync(tmp_path, transport)
    assert second.report.games_stored == 5
    assert repositories.games.count() == 5


def test_dedupe_across_overlapping_weeks(tmp_path: Path) -> None:
    payload = load("week_2024_w05_scoreboard.json")
    duplicate = {"events": [payload["events"][0]]}
    transport = build_transport(scoreboard_routes={4: duplicate, 5: payload})

    outcome, repositories, _trace = run_fixture_week_sync(tmp_path, transport, weeks=[4, 5])
    assert outcome.report.duplicates_removed == 1
    assert outcome.report.games_requested == 5
    assert outcome.report.games_stored == 5
    assert repositories.games.count() == 5


def test_coverage_ignores_postgame_timestamp_but_flags_admissible_leak() -> None:
    kickoff = datetime(2024, 9, 28, 23, 30, tzinfo=UTC)
    games = [
        CoverageGameRow(
            game_id="g1",
            season=2024,
            week=5,
            season_type=2,
            kickoff_utc=kickoff,
            home_team_id="1",
            away_team_id="2",
            is_fbs_vs_fbs=True,
        )
    ]
    fields = [
        CoverageFieldRow(
            game_id="g1",
            field_name="home_score",
            source="espn_postgame",
            value=31,
            known_at_utc=kickoff,
        ),
        CoverageFieldRow(
            game_id="g1",
            field_name="odds",
            source="espn",
            value={"favorite_source": "espn_open", "market_prob_source": "moneyline"},
            known_at_utc=kickoff,
        ),
    ]
    report = build_coverage(
        games,
        fields,
        seasons=[2024],
        season_types=[2],
        generated_at=NOW,
    )
    assert report.leaked_admissible_fields == 1
    assert not report.ok
    assert report.overall["odds"].pct == pytest.approx(100.0)
    assert report.favorite_sources == {"espn_open": 1}


def run_fixture_week_sync(tmp_path: Path, transport: FixtureTransport, **kwargs: object):
    import asyncio

    return asyncio.run(run_fixture_week(tmp_path, transport=transport, **kwargs))
