"""Research-side contracts: briefs, reports, and spec promotion.

A research provider returns prose plus a proposed rule. The orchestrator only
lets a report through the schema gate when that rule is operationalizable; the
``rejection_reason`` field makes a discarded candidate auditable rather than a
silent drop.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from cfb_upset.contracts.common import Citation, StrictModel, UTCDateTime
from cfb_upset.contracts.spec import PreconditionStatus, RuleSpec


class ResearchBrief(StrictModel):
    """The question sent to Deep Research (one per candidate precondition)."""

    candidate_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    threshold_hints: list[str] = Field(default_factory=list)
    moderators: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    query: str = Field(min_length=1)


class ResearchReport(StrictModel):
    """A provider's answer for exactly one candidate precondition.

    Either ``proposed_rule`` is present (the candidate is operationalizable) or
    ``rejection_reason`` explains why it is not. Both being present is allowed
    only when the report is explicitly rejected, so the gate can record the
    proposed but unusable rule.
    """

    report_id: str = Field(min_length=1)
    candidate_key: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    proposed_rule: RuleSpec | None = None
    required_fields: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    reported_effect_sizes: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None
    rejection_reason: str | None = None
    created_at: UTCDateTime

    @model_validator(mode="after")
    def _is_operationalizable_or_rejected(self) -> ResearchReport:
        if self.proposed_rule is None and not self.rejection_reason:
            raise ValueError("a report must include a rule or a rejection_reason")
        if self.proposed_rule is not None:
            if self.proposed_rule.field not in self.required_fields:
                raise ValueError("required_fields must include proposed_rule.field")
            if self.rejection_reason is None and not self.citations:
                raise ValueError("an accepted report must carry at least one citation")
        return self


class SpecPromotion(StrictModel):
    """The orchestrator's decision about one spec version."""

    spec_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: PreconditionStatus
    reason: str = Field(min_length=1)
    decided_at: UTCDateTime
    approved_by: str | None = None


class ValidatedPrecondition(StrictModel):
    """A promoted (or rejected) spec with its statistical evidence."""

    spec_id: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    status: PreconditionStatus
    acceptance: dict[str, Any] = Field(default_factory=dict)
    effect: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    valid_from: UTCDateTime
    reason: str = Field(min_length=1)
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def _validated_specs_are_cited(self) -> ValidatedPrecondition:
        if self.status is PreconditionStatus.VALIDATED and not self.citations:
            raise ValueError("a validated precondition must carry a citation")
        return self


class UpsetDefinition(str, Enum):
    """Sensitivity definitions required by the evaluation protocol."""

    ANY = "any"
    FAVORITE_BY_7 = "favorite_by_7"
    FAVORITE_BY_14 = "favorite_by_14"
