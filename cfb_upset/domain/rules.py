"""Deterministic rule DSL.

A rule is a whitelisted field, an operator, and a threshold. The evaluator is
pure: the same rule plus the same context always produces the same evidence.
Missing values are never treated as "false" by accident; the spec chooses an
explicit ``missing_policy``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cfb_upset.contracts import (
    MissingPolicy,
    PreconditionSpec,
    RuleEvidence,
    RuleOp,
    RuleSpec,
    ScreenState,
)
from cfb_upset.errors import ContractError


@dataclass(frozen=True)
class FieldSpec:
    """Type and unit metadata for one admitted rule field."""

    name: str
    kind: str  # "number" | "integer" | "boolean" | "string"
    units: str | None
    description: str


def _field(name: str, kind: str, units: str | None, description: str) -> FieldSpec:
    return FieldSpec(name=name, kind=kind, units=units, description=description)


# Phase 0 registry. Later phases extend this in one place; a spec that
# references an unknown field is rejected rather than silently unevaluable.
FIELD_REGISTRY: dict[str, FieldSpec] = {
    item.name: item
    for item in (
        _field("rest_days_home", "integer", "days", "Days since the home team's previous game"),
        _field("rest_days_away", "integer", "days", "Days since the away team's previous game"),
        _field(
            "travel_km_away", "number", "km", "Great-circle distance travelled by the away team"
        ),
        _field(
            "timezone_delta_away", "number", "hours", "Absolute time-zone shift for the away team"
        ),
        _field("rank_diff", "integer", "rank", "Favourite rank minus underdog rank"),
        _field("favorite_spread", "number", "points", "Pre-kickoff spread from the favourite"),
        _field("is_night_game", "boolean", None, "Kickoff at or after 18:00 local time"),
        _field("is_neutral_site", "boolean", None, "Game is not at either team's home venue"),
        _field("is_conference_game", "boolean", None, "Both teams share a conference"),
        _field("home_last3_win_pct", "number", "ratio", "Home team win rate over its last 3 games"),
        _field("away_last3_win_pct", "number", "ratio", "Away team win rate over its last 3 games"),
        _field("lookahead_next_rank", "integer", "rank", "Rank of the home team's next opponent"),
        _field("temperature_c", "number", "C", "Forecast temperature at kickoff"),
        _field("wind_kph", "number", "km/h", "Forecast wind speed at kickoff"),
        _field("altitude_m", "number", "m", "Venue altitude"),
        _field("short_week_home", "boolean", None, "Home team played within the previous 6 days"),
        _field("short_week_away", "boolean", None, "Away team played within the previous 6 days"),
    )
}


def require_field(field_name: str) -> FieldSpec:
    """Return field metadata or raise ``ContractError`` for an unknown field."""

    try:
        return FIELD_REGISTRY[field_name]
    except KeyError as exc:
        raise ContractError(f"unknown rule field {field_name!r}") from exc


def coerce_observed(field_name: str, value: Any) -> Any:
    """Coerce a raw context value to its registered type.

    Missing values (``None``/``NaN``) return ``None``. Uncoercible values raise
    ``ContractError``; the labeler turns that into an UNKNOWN label with a note.
    """

    spec = require_field(field_name)
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None

    if spec.kind == "number":
        if isinstance(value, bool):
            raise ContractError(f"field {field_name!r} expects a number, got bool")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"field {field_name!r} expects a number, got {value!r}") from exc

    if spec.kind == "integer":
        if isinstance(value, bool):
            raise ContractError(f"field {field_name!r} expects an integer, got bool")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"field {field_name!r} expects an integer, got {value!r}") from exc
        if not math.isfinite(number) or not number.is_integer():
            raise ContractError(f"field {field_name!r} expects an integer, got {value!r}")
        return int(number)

    if spec.kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ContractError(f"field {field_name!r} expects a boolean, got {value!r}")

    if spec.kind == "string":
        return str(value)
    raise ContractError(f"field {field_name!r} has an unsupported registry kind")


def _as_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{label} must be numeric, got bool")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} must be numeric, got {value!r}") from exc
    if not math.isfinite(number):
        raise ContractError(f"{label} must be finite, got {value!r}")
    return number


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def _missing_evidence(rule: RuleSpec, *, field: FieldSpec, observed: Any) -> RuleEvidence:
    state = (
        ScreenState.UNKNOWN if rule.missing_policy is MissingPolicy.UNKNOWN else ScreenState.FALSE
    )
    return RuleEvidence(
        field=rule.field,
        op=rule.op,
        threshold=rule.value,
        value2=rule.value2,
        observed=observed,
        units=rule.units or field.units,
        state=state,
        note="missing value",
    )


def evaluate_rule(
    rule: RuleSpec,
    context: Mapping[str, Any],
    *,
    known_at: datetime | None = None,
) -> RuleEvidence:
    """Evaluate one rule against a plain-value context.

    Args:
        rule: Validated rule DSL node.
        context: Field name -> raw value for one game.
        known_at: Optional timestamp recorded in the evidence trail.

    Returns:
        ``RuleEvidence`` whose ``state`` is TRUE, FALSE, or UNKNOWN.

    Raises:
        ContractError: The rule names an unknown field or has a malformed
            threshold. Data-level coercion failures become UNKNOWN evidence.
    """

    field = require_field(rule.field)
    raw_observed = context.get(rule.field)
    try:
        observed = coerce_observed(rule.field, raw_observed)
    except ContractError:
        return RuleEvidence(
            field=rule.field,
            op=rule.op,
            threshold=rule.value,
            value2=rule.value2,
            observed=raw_observed,
            units=rule.units or field.units,
            state=ScreenState.UNKNOWN,
            known_at=known_at,
            note="observed value could not be coerced",
        )

    if observed is None:
        evidence = _missing_evidence(rule, field=field, observed=observed)
        return evidence.model_copy(update={"known_at": known_at})

    op = rule.op
    state: bool
    if op in {RuleOp.GT, RuleOp.GE, RuleOp.LT, RuleOp.LE}:
        threshold = _as_number(rule.value, label=f"{rule.field} threshold")
        value = _as_number(observed, label=f"{rule.field} observed")
        state = {
            RuleOp.GT: value > threshold,
            RuleOp.GE: value >= threshold,
            RuleOp.LT: value < threshold,
            RuleOp.LE: value <= threshold,
        }[op]
    elif op is RuleOp.EQ:
        state = _values_equal(observed, rule.value)
    elif op is RuleOp.NE:
        state = not _values_equal(observed, rule.value)
    elif op in {RuleOp.IN, RuleOp.NOT_IN}:
        if not isinstance(rule.value, list):
            raise ContractError(f"'{op.value}' requires a list value")
        contained = any(_values_equal(observed, candidate) for candidate in rule.value)
        state = contained if op is RuleOp.IN else not contained
    elif op is RuleOp.BETWEEN:
        low = _as_number(rule.value, label=f"{rule.field} lower threshold")
        high = _as_number(rule.value2, label=f"{rule.field} upper threshold")
        value = _as_number(observed, label=f"{rule.field} observed")
        state = low <= value <= high
    elif op is RuleOp.IS_TRUE:
        if not isinstance(observed, bool):
            raise ContractError(f"'{op.value}' requires a boolean observation")
        state = observed
    elif op is RuleOp.IS_FALSE:
        if not isinstance(observed, bool):
            raise ContractError(f"'{op.value}' requires a boolean observation")
        state = not observed
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ContractError(f"unsupported operator {op!r}")

    return RuleEvidence(
        field=rule.field,
        op=op,
        threshold=rule.value,
        value2=rule.value2,
        observed=observed,
        units=rule.units or field.units,
        state=ScreenState.TRUE if state else ScreenState.FALSE,
        known_at=known_at,
    )


def evaluate_spec(
    spec: PreconditionSpec,
    context: Mapping[str, Any],
    *,
    known_at: datetime | None = None,
) -> RuleEvidence:
    """Evaluate a precondition's single rule and return its evidence."""

    return evaluate_rule(spec.rule, context, known_at=known_at)


def rule_hash(rule: RuleSpec) -> str:
    """Stable identity for deduplicating semantically identical rules."""

    from cfb_upset.ids import stable_hash

    return stable_hash(rule.model_dump(mode="json"))
