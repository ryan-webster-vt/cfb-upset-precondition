"""Scoring stub and stable ranking tests."""

from __future__ import annotations

from cfb_upset.contracts import ScreenMatch
from cfb_upset.domain.scoring import (
    STUB_BASE_RATE,
    STUB_MODEL_VERSION,
    rank_alerts,
    score_matches,
    utc_now,
)
from cfb_upset.domain.screen import screen_slate
from cfb_upset.fixtures.demo import demo_contexts, demo_games, demo_specs


def _matches() -> list[ScreenMatch]:
    return screen_slate(demo_games(), demo_specs(), demo_contexts())


def test_score_matches_skips_no_match_games() -> None:
    scores = score_matches(_matches(), demo_specs())

    assert set(scores) == {"401700001", "401700003"}
    assert scores["401700001"].probability == 0.38
    assert scores["401700003"].probability == 0.32
    assert scores["401700001"].model_version == STUB_MODEL_VERSION
    assert scores["401700001"].probability > STUB_BASE_RATE


def test_score_matches_clamps_probability_and_confidence() -> None:
    match = ScreenMatch(
        game_id="g",
        matched_specs=[],
        matched_count=0,
        evaluable_count=0,
        unknown_count=0,
    )
    assert score_matches([match], demo_specs()) == {}

    # 13 matched rules would exceed 0.95 without clamping; build the counts
    # directly because the fixture slate is intentionally small.
    from cfb_upset.contracts import MatchedSpec, RuleEvidence, RuleOp, ScreenState

    evidence = RuleEvidence(
        field="rest_days_away",
        op=RuleOp.LE,
        threshold=5,
        observed=4,
        state=ScreenState.TRUE,
    )
    matched = [
        MatchedSpec(spec_id=f"spec-{index}", version=1, title=f"Spec {index}", evidence=evidence)
        for index in range(13)
    ]
    big = ScreenMatch(
        game_id="g",
        matched_specs=matched,
        matched_count=13,
        evaluable_count=13,
        unknown_count=0,
    )
    scores = score_matches([big], demo_specs())

    assert scores["g"].probability == 0.95
    assert scores["g"].confidence == 0.90


def test_score_matches_deduplicates_citations() -> None:
    specs = demo_specs()
    scores = score_matches(_matches(), specs)
    alert_citations = scores["401700001"].citations

    urls = [citation.url for citation in alert_citations]
    assert len(urls) == len(set(urls))
    assert len(urls) == 3


def test_rank_alerts_is_total_and_stable() -> None:
    matches = _matches()
    games = demo_games()
    specs = demo_specs()
    scores = score_matches(matches, specs)

    first = rank_alerts(matches, games, specs, scores)
    second = rank_alerts(list(reversed(matches)), list(reversed(games)), specs, scores)

    assert [alert.game.game_id for alert in first] == [alert.game.game_id for alert in second]
    assert [alert.rank for alert in first] == [1, 2]
    assert [alert.score.probability for alert in first] == [0.38, 0.32]


def test_rank_alerts_tie_break_uses_kickoff_then_game_id() -> None:
    matches = _matches()
    games = demo_games()
    specs = demo_specs()
    scores = score_matches(matches, specs)

    # Give both candidates the same probability to exercise the tie-breaks.
    for score in scores.values():
        score.probability = 0.40

    alerts = rank_alerts(matches, games, specs, scores)

    # Both have three matched? No: 003 has two. Count wins before kickoff.
    assert [alert.game.game_id for alert in alerts] == ["401700001", "401700003"]


def test_rank_alerts_skips_missing_scores_or_games() -> None:
    matches = _matches()
    specs = demo_specs()
    games = demo_games()
    scores = score_matches(matches, specs)
    scores.pop("401700001")

    alerts = rank_alerts(matches, games, specs, scores)

    assert [alert.game.game_id for alert in alerts] == ["401700003"]


def test_rank_alerts_keeps_citations_tied_to_matched_specs() -> None:
    matches = _matches()
    alerts = rank_alerts(matches, demo_games(), demo_specs(), score_matches(matches, demo_specs()))

    top = alerts[0]
    expected = {
        citation.url
        for spec in demo_specs()
        if spec.spec_id in {matched.spec_id for matched in top.matched_specs}
        for citation in spec.citations
    }
    assert {citation.url for citation in top.citations} == expected


def test_utc_now_is_aware() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0
