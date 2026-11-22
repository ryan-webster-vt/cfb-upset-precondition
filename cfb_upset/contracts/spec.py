"""Precondition and rule contracts.

A precondition is only admissible if it can be encoded as a deterministic
``RuleSpec`` (field, operator, threshold, units). Free prose is rejected before
it reaches the spec store; that is the schema gate required by R9/R27.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from cfb_upset.contracts.common import Citation, StrictModel, UTCDateTime


class RuleOp(str, Enum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"


class MissingPolicy(str, Enum):
    UNKNOWN = "unknown"
    FALSE = "false"


class PreconditionStatus(str, Enum):
    VALIDATED = "validated"
    PROVISIONAL = "provisional"
    REJECTED = "rejected"


class RuleSpec(StrictModel):
    """A whitelisted, deterministic predicate over one admitted field."""

    field: str = Field(min_length=1)
    op: RuleOp
    value: Any = None
    value2: Any = None
    units: str | None = None
    missing_policy: MissingPolicy = MissingPolicy.UNKNOWN

    @model_validator(mode="after")
    def _check_operator_arity(self) -> RuleSpec:
        if self.op is RuleOp.BETWEEN and self.value2 is None:
            raise ValueError("'between' requires value2")
        if self.op in {RuleOp.IN, RuleOp.NOT_IN} and not isinstance(self.value, list):
            raise ValueError(f"'{self.op.value}' requires a list value")
        if self.op in {RuleOp.IS_TRUE, RuleOp.IS_FALSE}:
            if self.value is not None:
                raise ValueError(f"'{self.op.value}' does not take a value")
        if (
            self.op
            not in {
                RuleOp.IS_TRUE,
                RuleOp.IS_FALSE,
                RuleOp.IN,
                RuleOp.NOT_IN,
            }
            and self.value is None
        ):
            raise ValueError(f"'{self.op.value}' requires a value")
        return self


class PreconditionSpec(StrictModel):
    """A versioned, operationalizable upset precondition."""

    spec_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    candidate_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    rule: RuleSpec
    required_fields: list[str] = Field(min_length=1)
    scope: str = "FBS-vs-FBS"
    min_support: int = Field(default=30, ge=0)
    citations: list[Citation] = Field(default_factory=list)
    source: str = "seeded_literature"
    status: PreconditionStatus = PreconditionStatus.PROVISIONAL
    created_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def _required_fields_include_rule_field(self) -> PreconditionSpec:
        if self.rule.field not in self.required_fields:
            raise ValueError("required_fields must include rule.field")
        if self.status is PreconditionStatus.VALIDATED and not self.citations:
            raise ValueError("a validated precondition must carry at least one citation")
        return self
