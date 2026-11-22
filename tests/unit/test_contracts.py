"""Pydantic contracts: strictness, timezone handling, and invariants."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from cfb_upset.contracts import (
    AgentEvent,
    Citation,
    FavoriteSource,
    MatchedSpec,
    MissingPolicy,
    OddsInfo,
    PreconditionSpec,
    PreconditionStatus,
    Provenance,
    RankedAlert,
    RuleEvidence,
    RuleOp,
    RuleSpec,
    ScreenMatch,
    ScreenState,
    SlateGame,
    UpsetScore,
    WeatherInfo,
)
from cfb_upset.contracts.export import MODELS
from cfb_upset.fixtures.demo import demo_games, demo_specs

UTC = UTC
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def _game() -> SlateGame:
    return demo_games()[0]


def test_strict_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Citation(title="Source", url="https://example.com", unexpected=True)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Provenance(source="test", known_at=datetime(2026, 11, 27, 12, 0))


def test_aware_datetimes_are_normalised_to_utc() -> None:
    provenance = Provenance(
        source="test",
        known_at=datetime(2026, 11, 27, 7, 0, tzinfo=timezone(timedelta(hours=-5))),
    )
    assert provenance.known_at.hour == 12
    assert provenance.known_at.utcoffset().total_seconds() == 0


def test_citation_requires_http_url() -> None:
    with pytest.raises(ValidationError, match="must start with http"):
        Citation(title="Source", url="example.com/story")
    with pytest.raises(ValidationError, match="at least 1 character"):
        Citation(title="", url="https://example.com")


def test_odds_bounds() -> None:
    with pytest.raises(ValidationError):
        OddsInfo(favorite_source=FavoriteSource.ESPN_OPEN, known_at=NOW, market_prob=1.5)


def test_weather_bounds() -> None:
    with pytest.raises(ValidationError):
        WeatherInfo(wind_kph=-1.0, lead_hours=6.0)
    with pytest.raises(ValidationError):
        WeatherInfo(lead_hours=200.0)


@pytest.mark.parametrize(
    ("rule_kwargs", "message"),
    [
        ({"op": RuleOp.BETWEEN, "value": 1}, "requires value2"),
        ({"op": RuleOp.IN, "value": 1}, "requires a list"),
        ({"op": RuleOp.IS_TRUE, "value": True}, "does not take a value"),
        ({"op": RuleOp.GT}, "requires a value"),
    ],
)
def test_rule_operator_arity(rule_kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RuleSpec(field="rest_days_away", **rule_kwargs)


def test_rule_spec_defaults() -> None:
    rule = RuleSpec(field="rest_days_away", op=RuleOp.LE, value=5)
    assert rule.missing_policy is MissingPolicy.UNKNOWN
    assert rule.value2 is None
    assert rule.units is None


def test_precondition_requires_rule_field_in_required_fields() -> None:
    with pytest.raises(ValidationError, match="required_fields must include rule.field"):
        PreconditionSpec(
            spec_id="spec-bad",
            candidate_key="bad",
            title="Bad spec",
            rationale="Bad.",
            rule=RuleSpec(field="rest_days_away", op=RuleOp.LE, value=5),
            required_fields=["travel_km_away"],
        )


def test_validated_precondition_requires_citation() -> None:
    with pytest.raises(ValidationError, match="must carry at least one citation"):
        PreconditionSpec(
            spec_id="spec-bad",
            candidate_key="bad",
            title="Bad spec",
            rationale="Bad.",
            rule=RuleSpec(field="rest_days_away", op=RuleOp.LE, value=5),
            required_fields=["rest_days_away"],
            status=PreconditionStatus.VALIDATED,
        )


def test_validated_demo_specs_have_citations() -> None:
    assert all(spec.status is PreconditionStatus.VALIDATED for spec in demo_specs())
    assert all(spec.citations for spec in demo_specs())


def _evidence(state: ScreenState = ScreenState.TRUE) -> RuleEvidence:
    return RuleEvidence(
        field="rest_days_away",
        op=RuleOp.LE,
        threshold=5,
        observed=4,
        state=state,
    )


def _matched(spec_id: str = "spec-away-short-rest") -> MatchedSpec:
    return MatchedSpec(
        spec_id=spec_id,
        version=1,
        title="Away team on short rest",
        evidence=_evidence(),
    )


def test_screen_match_counts_must_agree() -> None:
    with pytest.raises(ValidationError, match="matched_count must equal"):
        ScreenMatch(
            game_id="g",
            matched_specs=[_matched()],
            matched_count=0,
            evaluable_count=1,
            unknown_count=0,
        )
    with pytest.raises(ValidationError, match="cannot exceed evaluable_count"):
        ScreenMatch(
            game_id="g",
            matched_specs=[_matched()],
            matched_count=1,
            evaluable_count=0,
            unknown_count=0,
        )


def test_screen_match_rejects_duplicate_specs() -> None:
    with pytest.raises(ValidationError, match="duplicate matched spec_id"):
        ScreenMatch(
            game_id="g",
            matched_specs=[_matched(), _matched()],
            matched_count=2,
            evaluable_count=2,
            unknown_count=0,
        )


def _score(game_id: str) -> UpsetScore:
    return UpsetScore(
        game_id=game_id,
        probability=0.38,
        confidence=0.71,
        backend="calibrated_rules",
        model_version="test",
        rationale="test",
    )


def test_ranked_alert_score_must_belong_to_game() -> None:
    with pytest.raises(ValidationError, match="score.game_id must match"):
        RankedAlert(
            rank=1,
            game=_game(),
            score=_score("different-game"),
            rationale="test",
        )


def test_agent_event_shape() -> None:
    event = AgentEvent(
        event_id="event-1",
        run_id="run-1",
        agent="Upset-Scorer",
        phase="score",
        event_type="scored",
        payload={"alerts": 2},
        ts=NOW,
    )
    assert event.model_dump(mode="json")["ts"] == "2026-11-27T12:00:00Z"


def test_slate_game_display_name() -> None:
    assert _game().display_name == "Miami at Virginia Tech"
    assert _game().slate_date == date(2026, 11, 28)


def test_contract_schema_export_catalogue_is_complete() -> None:
    expected = {
        "AgentEvent",
        "Citation",
        "OddsInfo",
        "PreconditionSpec",
        "Provenance",
        "RankedAlert",
        "RuleSpec",
        "RunResult",
        "ScreenMatch",
        "SlateGame",
        "UpsetScore",
    }
    assert expected <= set(MODELS)
    for model in MODELS.values():
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
