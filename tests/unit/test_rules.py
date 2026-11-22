"""Deterministic rule DSL: coercion, operators, and missing-value semantics."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from cfb_upset.contracts import MissingPolicy, PreconditionSpec, RuleOp, RuleSpec, ScreenState
from cfb_upset.domain.rules import (
    FIELD_REGISTRY,
    FieldSpec,
    coerce_observed,
    evaluate_rule,
    evaluate_spec,
    require_field,
    rule_hash,
)
from cfb_upset.errors import ContractError

KNOWN_AT = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def make_rule(
    field: str,
    op: RuleOp,
    *,
    value: object = None,
    value2: object = None,
    missing_policy: MissingPolicy = MissingPolicy.UNKNOWN,
    units: str | None = None,
) -> RuleSpec:
    return RuleSpec(
        field=field,
        op=op,
        value=value,
        value2=value2,
        missing_policy=missing_policy,
        units=units,
    )


# --- registry and coercion -------------------------------------------------


def test_registry_has_typed_fields_and_units() -> None:
    spec = require_field("rest_days_away")
    assert spec.kind == "integer"
    assert spec.units == "days"
    assert FIELD_REGISTRY["travel_km_away"].kind == "number"
    assert FIELD_REGISTRY["is_night_game"].kind == "boolean"


def test_unknown_field_raises_contract_error() -> None:
    with pytest.raises(ContractError, match="unknown rule field"):
        require_field("not_a_field")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (4, 4.0),
        ("4.5", 4.5),
        (None, None),
        (math.nan, None),
    ],
)
def test_coerce_number(raw: object, expected: float | None) -> None:
    assert coerce_observed("travel_km_away", raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(4, 4), (4.0, 4), ("7", 7), (None, None), (math.nan, None)],
)
def test_coerce_integer(raw: object, expected: int | None) -> None:
    assert coerce_observed("rest_days_away", raw) == expected


@pytest.mark.parametrize("raw", [4.5, "4.5", "many", True])
def test_coerce_integer_rejects_non_integers(raw: object) -> None:
    with pytest.raises(ContractError):
        coerce_observed("rest_days_away", raw)


@pytest.mark.parametrize("raw", [True, False, "true", "YES", "1", 1, 0, "no", "false", "0"])
def test_coerce_boolean_accepts_common_forms(raw: object) -> None:
    assert coerce_observed("is_night_game", raw) is (
        str(raw).strip().lower() in {"1", "true", "yes"}
    )


@pytest.mark.parametrize("raw", [2, "maybe", 1.0, object()])
def test_coerce_boolean_rejects_ambiguous_values(raw: object) -> None:
    with pytest.raises(ContractError):
        coerce_observed("is_night_game", raw)


def test_coerce_number_rejects_bool_and_garbage() -> None:
    with pytest.raises(ContractError, match="got bool"):
        coerce_observed("travel_km_away", True)
    with pytest.raises(ContractError, match="expects a number"):
        coerce_observed("travel_km_away", "far")


def test_coerce_string_and_unsupported_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(FIELD_REGISTRY, "label", FieldSpec("label", "string", None, "test"))
    assert coerce_observed("label", 7) == "7"

    monkeypatch.setitem(FIELD_REGISTRY, "mystery", FieldSpec("mystery", "complex", None, "test"))
    with pytest.raises(ContractError, match="unsupported registry kind"):
        coerce_observed("mystery", 1)


# --- comparison operators --------------------------------------------------


@pytest.mark.parametrize(
    ("op", "value", "observed", "expected"),
    [
        (RuleOp.GT, 3, 4, True),
        (RuleOp.GT, 3, 3, False),
        (RuleOp.GE, 3, 3, True),
        (RuleOp.GE, 3, 2, False),
        (RuleOp.LT, 3, 2, True),
        (RuleOp.LT, 3, 3, False),
        (RuleOp.LE, 3, 3, True),
        (RuleOp.LE, 3, 4, False),
    ],
)
def test_numeric_comparisons(op: RuleOp, value: float, observed: float, expected: bool) -> None:
    evidence = evaluate_rule(
        make_rule("rest_days_away", op, value=value),
        {"rest_days_away": observed},
        known_at=KNOWN_AT,
    )
    assert evidence.state is (ScreenState.TRUE if expected else ScreenState.FALSE)
    assert evidence.observed == observed
    assert evidence.threshold == value
    assert evidence.units == "days"
    assert evidence.known_at == KNOWN_AT


def test_between_is_inclusive() -> None:
    rule = make_rule("rest_days_away", RuleOp.BETWEEN, value=4, value2=6)
    assert evaluate_rule(rule, {"rest_days_away": 4}).state is ScreenState.TRUE
    assert evaluate_rule(rule, {"rest_days_away": 6}).state is ScreenState.TRUE
    assert evaluate_rule(rule, {"rest_days_away": 7}).state is ScreenState.FALSE


def test_eq_and_ne_use_type_aware_equality() -> None:
    eq = make_rule("rest_days_away", RuleOp.EQ, value=4)
    ne = make_rule("rest_days_away", RuleOp.NE, value=4)
    assert evaluate_rule(eq, {"rest_days_away": 4.0}).state is ScreenState.TRUE
    assert evaluate_rule(ne, {"rest_days_away": 5}).state is ScreenState.TRUE
    assert evaluate_rule(ne, {"rest_days_away": 4}).state is ScreenState.FALSE


def test_bool_eq_is_identity_not_truthiness() -> None:
    rule = make_rule("is_night_game", RuleOp.EQ, value=True)
    assert evaluate_rule(rule, {"is_night_game": True}).state is ScreenState.TRUE
    assert evaluate_rule(rule, {"is_night_game": False}).state is ScreenState.FALSE
    assert evaluate_rule(rule, {"is_night_game": 1}).state is ScreenState.TRUE


def test_string_eq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(FIELD_REGISTRY, "label", FieldSpec("label", "string", None, "test"))
    rule = make_rule("label", RuleOp.EQ, value="home")
    assert evaluate_rule(rule, {"label": "home"}).state is ScreenState.TRUE
    assert evaluate_rule(rule, {"label": "away"}).state is ScreenState.FALSE


def test_in_and_not_in() -> None:
    in_rule = make_rule("rest_days_away", RuleOp.IN, value=[3, 4, 5])
    not_in_rule = make_rule("rest_days_away", RuleOp.NOT_IN, value=[3, 4, 5])
    assert evaluate_rule(in_rule, {"rest_days_away": 4}).state is ScreenState.TRUE
    assert evaluate_rule(in_rule, {"rest_days_away": 7}).state is ScreenState.FALSE
    assert evaluate_rule(not_in_rule, {"rest_days_away": 7}).state is ScreenState.TRUE
    assert evaluate_rule(not_in_rule, {"rest_days_away": 4}).state is ScreenState.FALSE


def test_is_true_and_is_false() -> None:
    true_rule = make_rule("is_night_game", RuleOp.IS_TRUE)
    false_rule = make_rule("is_night_game", RuleOp.IS_FALSE)
    assert evaluate_rule(true_rule, {"is_night_game": True}).state is ScreenState.TRUE
    assert evaluate_rule(true_rule, {"is_night_game": False}).state is ScreenState.FALSE
    assert evaluate_rule(false_rule, {"is_night_game": False}).state is ScreenState.TRUE
    assert evaluate_rule(false_rule, {"is_night_game": True}).state is ScreenState.FALSE


# --- missing values and malformed data -------------------------------------


@pytest.mark.parametrize("context", [{}, {"rest_days_away": None}, {"rest_days_away": math.nan}])
def test_missing_value_unknown_policy(context: dict[str, object]) -> None:
    evidence = evaluate_rule(
        make_rule("rest_days_away", RuleOp.LE, value=5), context, known_at=KNOWN_AT
    )
    assert evidence.state is ScreenState.UNKNOWN
    assert evidence.note == "missing value"
    assert evidence.known_at == KNOWN_AT


def test_missing_value_false_policy() -> None:
    evidence = evaluate_rule(
        make_rule(
            "rest_days_away",
            RuleOp.LE,
            value=5,
            missing_policy=MissingPolicy.FALSE,
        ),
        {},
    )
    assert evidence.state is ScreenState.FALSE
    assert evidence.note == "missing value"


def test_uncoercible_observation_becomes_unknown() -> None:
    evidence = evaluate_rule(
        make_rule("rest_days_away", RuleOp.LE, value=5),
        {"rest_days_away": "many"},
        known_at=KNOWN_AT,
    )
    assert evidence.state is ScreenState.UNKNOWN
    assert evidence.observed == "many"
    assert evidence.note == "observed value could not be coerced"
    assert evidence.known_at == KNOWN_AT


def test_nan_threshold_is_rejected() -> None:
    with pytest.raises(ContractError, match="must be finite"):
        evaluate_rule(
            make_rule("rest_days_away", RuleOp.GT, value=math.inf),
            {"rest_days_away": 4},
        )


def test_bool_threshold_is_rejected() -> None:
    with pytest.raises(ContractError, match="must be numeric, got bool"):
        evaluate_rule(
            make_rule("rest_days_away", RuleOp.GT, value=True),
            {"rest_days_away": 4},
        )


def test_non_numeric_threshold_is_rejected() -> None:
    with pytest.raises(ContractError, match="must be numeric"):
        evaluate_rule(
            make_rule("rest_days_away", RuleOp.GT, value="high"),
            {"rest_days_away": 4},
        )


def test_unknown_field_in_rule_raises() -> None:
    with pytest.raises(ContractError, match="unknown rule field"):
        evaluate_rule(make_rule("not_a_field", RuleOp.GT, value=1), {"not_a_field": 2})


# --- spec evaluation and hashing -------------------------------------------


def test_evaluate_spec_delegates_to_rule() -> None:
    spec = PreconditionSpec(
        spec_id="spec-test",
        candidate_key="test",
        title="Test spec",
        rationale="Because it is a test.",
        rule=make_rule("rest_days_away", RuleOp.LE, value=5),
        required_fields=["rest_days_away"],
    )
    evidence = evaluate_spec(spec, {"rest_days_away": 4}, known_at=KNOWN_AT)
    assert evidence.state is ScreenState.TRUE
    assert evidence.known_at == KNOWN_AT


def test_rule_hash_is_stable_and_value_sensitive() -> None:
    left = make_rule("rest_days_away", RuleOp.LE, value=5)
    same = make_rule("rest_days_away", RuleOp.LE, value=5)
    different = make_rule("rest_days_away", RuleOp.LE, value=6)

    assert rule_hash(left) == rule_hash(same)
    assert rule_hash(left) != rule_hash(different)
    assert len(rule_hash(left)) == 64
