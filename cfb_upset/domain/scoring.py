"""Deterministic Phase 0 scorer stub and stable ranking.

This is deliberately *not* an LLM. It gives the walking skeleton a real,
repeatable score so the UI and contracts can be exercised end to end. P8
replaces the internals while keeping ``UpsetScore`` and ``RankedAlert``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from cfb_upset.contracts import (
    Citation,
    PreconditionSpec,
    RankedAlert,
    ScoreBackend,
    ScreenMatch,
    SlateGame,
    UpsetScore,
)

STUB_BASE_RATE = 0.20
STUB_MODEL_VERSION = "stub-p0-rule-count"


def score_matches(
    matches: Iterable[ScreenMatch],
    specs: Iterable[PreconditionSpec],
    *,
    base_rate: float = STUB_BASE_RATE,
) -> dict[str, UpsetScore]:
    """Score every game that tripped at least one precondition.

    Probability is the slate base rate plus a fixed increment per matched rule.
    The increment is a placeholder, not a validated effect; the rationale and
    model version say so explicitly.
    """

    spec_by_id = {spec.spec_id: spec for spec in specs}
    scores: dict[str, UpsetScore] = {}

    for match in matches:
        if match.matched_count == 0:
            continue
        probability = min(0.95, base_rate + 0.06 * match.matched_count)
        confidence = min(0.90, 0.35 + 0.12 * match.matched_count)
        citations: list[Citation] = []
        seen_urls: set[str] = set()
        for matched in match.matched_specs:
            spec = spec_by_id.get(matched.spec_id)
            if spec is None:
                continue
            for citation in spec.citations:
                if citation.url not in seen_urls:
                    citations.append(citation)
                    seen_urls.add(citation.url)

        titles = [matched.title for matched in match.matched_specs]
        rationale = (
            f"Matched {match.matched_count} precondition(s): {', '.join(titles)}. "
            "Phase 0 uses a deterministic base-rate + rule-count stub; "
            "this is not yet a trained probability."
        )
        scores[match.game_id] = UpsetScore(
            game_id=match.game_id,
            probability=round(probability, 4),
            raw_probability=round(probability, 4),
            confidence=round(confidence, 4),
            key_signals=titles,
            citations=citations,
            backend=ScoreBackend.CALIBRATED_RULES,
            model_version=STUB_MODEL_VERSION,
            rationale=rationale,
        )
    return scores


def rank_alerts(
    matches: Iterable[ScreenMatch],
    games: Iterable[SlateGame],
    specs: Iterable[PreconditionSpec],
    scores: Mapping[str, UpsetScore],
) -> list[RankedAlert]:
    """Return a total, stable 1..n ordering of scored candidates.

    Tie-breaks are probability desc, matched-spec count desc, kickoff, game id,
    so two runs over the same inputs cannot swap ranks.
    """

    games_by_id = {game.game_id: game for game in games}
    spec_by_id = {spec.spec_id: spec for spec in specs}
    candidates = [
        match
        for match in matches
        if match.matched_count > 0 and match.game_id in scores and match.game_id in games_by_id
    ]
    candidates.sort(
        key=lambda match: (
            -scores[match.game_id].probability,
            -match.matched_count,
            games_by_id[match.game_id].kickoff_utc,
            match.game_id,
        )
    )

    alerts: list[RankedAlert] = []
    for rank, match in enumerate(candidates, start=1):
        game = games_by_id[match.game_id]
        score = scores[match.game_id]
        # Keep the alert's citation list tied to the matched specs, not to any
        # future prose rewrite.
        citations: list[Citation] = []
        seen_urls: set[str] = set()
        for matched in match.matched_specs:
            spec = spec_by_id.get(matched.spec_id)
            if spec is None:
                continue
            for citation in spec.citations:
                if citation.url not in seen_urls:
                    citations.append(citation)
                    seen_urls.add(citation.url)
        alerts.append(
            RankedAlert(
                rank=rank,
                game=game,
                score=score,
                rationale=score.rationale,
                citations=citations,
                matched_specs=list(match.matched_specs),
            )
        )
    return alerts


def utc_now() -> datetime:
    """Small helper kept here so callers do not import timezone everywhere."""

    return datetime.now(UTC)
