"""Deterministic slate screening.

Screening happens *before* any web research. It reuses the same evaluator as the
historical labeler, so a rule cannot mean one thing during validation and a
different thing at monitor time (R29).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from cfb_upset.contracts import (
    MatchedSpec,
    PreconditionSpec,
    ScreenMatch,
    ScreenState,
    SlateGame,
)
from cfb_upset.domain.rules import evaluate_spec


def screen_game(
    game: SlateGame,
    specs: Iterable[PreconditionSpec],
    context: Mapping[str, object],
    *,
    known_at: datetime | None = None,
) -> ScreenMatch:
    """Evaluate every spec against one game and report the matches."""

    ordered_specs = sorted(specs, key=lambda spec: (spec.spec_id, spec.version))
    matched: list[MatchedSpec] = []
    evaluable = 0
    unknown = 0

    for spec in ordered_specs:
        evidence = evaluate_spec(spec, context, known_at=known_at)
        if evidence.state is ScreenState.UNKNOWN:
            unknown += 1
            continue
        evaluable += 1
        if evidence.state is ScreenState.TRUE:
            matched.append(
                MatchedSpec(
                    spec_id=spec.spec_id,
                    version=spec.version,
                    title=spec.title,
                    evidence=evidence,
                )
            )

    return ScreenMatch(
        game_id=game.game_id,
        matched_specs=matched,
        matched_count=len(matched),
        evaluable_count=evaluable,
        unknown_count=unknown,
    )


def screen_slate(
    games: Iterable[SlateGame],
    specs: Iterable[PreconditionSpec],
    contexts: Mapping[str, Mapping[str, object]],
    *,
    known_at_by_game: Mapping[str, datetime] | None = None,
) -> list[ScreenMatch]:
    """Screen a whole slate in deterministic kickoff order."""

    ordered_games = sorted(games, key=lambda game: (game.kickoff_utc, game.game_id))
    known_at_by_game = known_at_by_game or {}
    spec_list = list(specs)
    return [
        screen_game(
            game,
            spec_list,
            contexts.get(game.game_id, {}),
            known_at=known_at_by_game.get(game.game_id),
        )
        for game in ordered_games
    ]


def matched_game_ids(matches: Iterable[ScreenMatch]) -> list[str]:
    """Return ids of games tripping at least one rule, preserving input order."""

    return [match.game_id for match in matches if match.matched_count > 0]
