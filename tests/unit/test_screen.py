"""Slate screening: counts, ordering, missing values, and evidence reuse."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cfb_upset.contracts import (
    MissingPolicy,
    PreconditionSpec,
    RuleOp,
    RuleSpec,
    ScreenState,
)
from cfb_upset.domain.screen import matched_game_ids, screen_game, screen_slate
from cfb_upset.fixtures.demo import demo_contexts, demo_games, demo_specs

UTC = UTC


def test_screen_game_reports_matches_and_counts() -> None:
    game = next(game for game in demo_games() if game.game_id == "401700001")
    match = screen_game(game, demo_specs(), demo_contexts()["401700001"])

    assert match.game_id == "401700001"
    assert match.matched_count == 3
    assert match.evaluable_count == 3
    assert match.unknown_count == 0
    assert [item.spec_id for item in match.matched_specs] == [
        "spec-away-long-travel",
        "spec-away-short-rest",
        "spec-home-lookahead",
    ]
    assert all(item.evidence.state is ScreenState.TRUE for item in match.matched_specs)


def test_screen_game_can_match_nothing() -> None:
    game = next(game for game in demo_games() if game.game_id == "401700002")
    match = screen_game(game, demo_specs(), demo_contexts()["401700002"])

    assert match.matched_count == 0
    assert match.evaluable_count == 3
    assert match.unknown_count == 0
    assert match.matched_specs == []


def test_screen_game_partial_match() -> None:
    game = next(game for game in demo_games() if game.game_id == "401700003")
    match = screen_game(game, demo_specs(), demo_contexts()["401700003"])

    assert match.matched_count == 2
    assert match.evaluable_count == 3
    assert [item.spec_id for item in match.matched_specs] == [
        "spec-away-long-travel",
        "spec-away-short-rest",
    ]


def test_missing_context_is_unknown_and_not_evaluable() -> None:
    game = demo_games()[0]
    match = screen_game(game, demo_specs(), {})

    assert match.matched_count == 0
    assert match.evaluable_count == 0
    assert match.unknown_count == 3


def test_missing_policy_false_counts_as_evaluable() -> None:
    game = demo_games()[0]
    spec = PreconditionSpec(
        spec_id="spec-missing-false",
        candidate_key="missing_false",
        title="Missing value is false",
        rationale="A missing value should not trip this rule.",
        rule=RuleSpec(
            field="rest_days_away",
            op=RuleOp.LE,
            value=5,
            missing_policy=MissingPolicy.FALSE,
        ),
        required_fields=["rest_days_away"],
    )

    match = screen_game(game, [spec], {})

    assert match.matched_count == 0
    assert match.evaluable_count == 1
    assert match.unknown_count == 0


def test_specs_are_evaluated_in_stable_id_order() -> None:
    game = demo_games()[0]
    specs = list(reversed(demo_specs()))
    match = screen_game(game, specs, demo_contexts()[game.game_id])

    ids = [item.spec_id for item in match.matched_specs]
    assert ids == sorted(ids)


def test_known_at_is_recorded_per_game() -> None:
    known_at = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    game = demo_games()[0]
    match = screen_game(
        game,
        demo_specs(),
        demo_contexts()[game.game_id],
        known_at=known_at,
    )

    assert all(item.evidence.known_at == known_at for item in match.matched_specs)


def test_screen_slate_orders_by_kickoff_then_id() -> None:
    games = list(reversed(demo_games()))
    matches = screen_slate(games, demo_specs(), demo_contexts())

    assert [match.game_id for match in matches] == [
        "401700001",
        "401700002",
        "401700003",
    ]


def test_screen_slate_same_kickoff_uses_game_id() -> None:
    games = demo_games()
    first, second = games[0], games[1]
    second = second.model_copy(update={"kickoff_utc": first.kickoff_utc, "game_id": "000000001"})
    games = [first, second]

    matches = screen_slate(games, demo_specs(), demo_contexts())

    assert [match.game_id for match in matches] == ["000000001", "401700001"]


def test_screen_slate_passes_known_at_by_game() -> None:
    known_at = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    matches = screen_slate(
        demo_games()[:1],
        demo_specs(),
        demo_contexts(),
        known_at_by_game={"401700001": known_at},
    )

    assert all(item.evidence.known_at == known_at for item in matches[0].matched_specs)


def test_screen_slate_tolerates_unknown_game_context() -> None:
    matches = screen_slate(demo_games(), demo_specs(), {})

    assert [match.matched_count for match in matches] == [0, 0, 0]
    assert [match.unknown_count for match in matches] == [3, 3, 3]


def test_matched_game_ids_preserves_input_order() -> None:
    matches = screen_slate(demo_games(), demo_specs(), demo_contexts())

    assert matched_game_ids(matches) == ["401700001", "401700003"]
    assert matched_game_ids(reversed(matches)) == ["401700003", "401700001"]


def test_screen_game_duplicate_spec_ids_are_rejected() -> None:
    spec = demo_specs()[0]
    with pytest.raises(ValueError, match="duplicate matched spec_id"):
        screen_game(
            demo_games()[0],
            [spec, spec],
            {"rest_days_away": 4, "travel_km_away": 0, "lookahead_next_rank": 99},
        )
