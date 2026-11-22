"""Walking skeleton: deterministic pipeline, ranking, and agent timeline."""

from __future__ import annotations

from datetime import date

from cfb_upset.fixtures.demo import demo_contexts, demo_games, demo_specs
from cfb_upset.pipelines.skeleton import run_walking_skeleton


def test_skeleton_produces_ranked_alerts_and_timeline() -> None:
    result = run_walking_skeleton(
        demo_games(),
        demo_specs(),
        demo_contexts(),
        run_id="run-test",
    )

    assert result.status.value == "completed"
    assert result.degraded is False
    assert result.reason is None
    assert [alert.rank for alert in result.alerts] == [1, 2]
    assert [alert.game.game_id for alert in result.alerts] == ["401700001", "401700003"]
    assert [alert.score.probability for alert in result.alerts] == [0.38, 0.32]
    assert [alert.score.confidence for alert in result.alerts] == [0.71, 0.59]
    assert all(alert.score.backend.value == "calibrated_rules" for alert in result.alerts)
    assert all(alert.citations for alert in result.alerts)
    assert all(alert.matched_specs for alert in result.alerts)


def test_skeleton_timeline_covers_three_agents() -> None:
    result = run_walking_skeleton(
        demo_games(),
        demo_specs(),
        demo_contexts(),
        run_id="run-test",
    )

    agents = [event.agent for event in result.events]
    assert len(set(agents)) >= 3
    assert set(agents) == {
        "Monitor-Orchestrator",
        "Deterministic-Rule-Screen",
        "Upset-Scorer",
    }
    assert all(event.run_id == "run-test" for event in result.events)
    assert [event.event_type for event in result.events] == [
        "run_started",
        "screen_started",
        "screen_completed",
        "confirmation_skipped",
        "scoring_started",
        "alerts_ranked",
        "run_completed",
    ]


def test_skeleton_returns_empty_state_when_nothing_matches() -> None:
    game = next(game for game in demo_games() if game.game_id == "401700002")
    result = run_walking_skeleton([game], demo_specs(), demo_contexts(), run_id="run-empty")

    assert result.status.value == "no_preconditions_matched"
    assert result.alerts == []
    assert result.reason == "No upset alerts for this slate"
    assert [event.event_type for event in result.events][-2:] == [
        "scoring_skipped",
        "run_completed",
    ]
    assert result.matches[0].matched_count == 0


def test_skeleton_empty_slate_uses_today() -> None:
    result = run_walking_skeleton([], demo_specs(), {}, run_id="run-empty")

    assert result.slate_date == date.today()
    assert result.status.value == "no_preconditions_matched"
    assert result.alerts == []


def test_skeleton_base_rate_changes_probability() -> None:
    result = run_walking_skeleton(
        demo_games()[:1],
        demo_specs(),
        demo_contexts(),
        run_id="run-base",
        base_rate=0.30,
    )

    assert result.alerts[0].score.probability == 0.48


def test_skeleton_ranking_is_deterministic_for_same_inputs() -> None:
    first = run_walking_skeleton(demo_games(), demo_specs(), demo_contexts(), run_id="run-a")
    second = run_walking_skeleton(demo_games(), demo_specs(), demo_contexts(), run_id="run-b")

    assert [alert.game.game_id for alert in first.alerts] == [
        alert.game.game_id for alert in second.alerts
    ]
    assert [alert.score.probability for alert in first.alerts] == [
        alert.score.probability for alert in second.alerts
    ]
    assert [event.event_type for event in first.events] == [
        event.event_type for event in second.events
    ]
