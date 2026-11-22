"""Every Phase 1 contract is strict, typed, and rejects malformed payloads."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cfb_upset.contracts import (
    Citation,
    ConfirmedFlag,
    DatasetSplit,
    FetchedPage,
    GameIdBatch,
    HistoricalGameRecord,
    IngestReport,
    LabeledGame,
    LabelEvidence,
    MonitorDecision,
    MonitorDecisionType,
    QuarantineRecord,
    ResearchBrief,
    ResearchReport,
    RuleEvidence,
    RuleOp,
    RuleSpec,
    ScreenState,
    SearchHit,
    SpecPromotion,
    StatResult,
    TeamInfo,
    ValidatedPrecondition,
)
from cfb_upset.contracts.export import MODELS
from cfb_upset.contracts.spec import PreconditionStatus
from cfb_upset.fixtures.demo import demo_games, demo_specs

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
CITATION = Citation(
    title="Short rest and upset risk",
    url="https://www.espn.com/college-football/story/1",
    published_at=NOW,
)
TEAM_HOME = TeamInfo(team_id="1", school="Home")
TEAM_AWAY = TeamInfo(team_id="2", school="Away")


def _extra_rejected(model, payload: dict) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({**payload, "unexpected_field": True})


def test_every_exported_model_forbids_extra_fields() -> None:
    for name, model in MODELS.items():
        assert model.model_config.get("extra") == "forbid", name
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False, name


def test_history_contracts_reject_extra_fields() -> None:
    record = {
        "game_id": "g1",
        "season": 2025,
        "kickoff_utc": NOW,
        "home": TEAM_HOME.model_dump(),
        "away": TEAM_AWAY.model_dump(),
        "fetched_at": NOW,
    }
    _extra_rejected(HistoricalGameRecord, record)
    _extra_rejected(GameIdBatch, {"batch_id": "b1", "game_ids": ["g1"]})
    _extra_rejected(
        IngestReport,
        {
            "report_id": "r1",
            "games_requested": 1,
            "games_stored": 1,
            "started_at": NOW,
            "finished_at": NOW,
        },
    )
    _extra_rejected(QuarantineRecord, {"record_id": "q1", "errors": ["bad"], "created_at": NOW})


def test_history_invariants() -> None:
    with pytest.raises(ValidationError, match="winner_team_id"):
        HistoricalGameRecord(
            game_id="g1",
            season=2025,
            kickoff_utc=NOW,
            home=TEAM_HOME,
            away=TEAM_AWAY,
            winner_team_id="3",
            fetched_at=NOW,
        )
    with pytest.raises(ValidationError, match="game_ids must be unique"):
        GameIdBatch(batch_id="b1", game_ids=["g1", "g1"])
    with pytest.raises(ValidationError, match="stored \\+ quarantined"):
        IngestReport(
            report_id="r1",
            games_requested=1,
            games_stored=1,
            quarantined=1,
            started_at=NOW,
            finished_at=NOW,
        )
    with pytest.raises(ValidationError, match="finished_at"):
        IngestReport(report_id="r1", started_at=NOW, finished_at=NOW.replace(year=2025))


def test_label_and_stat_contracts_reject_extra_fields() -> None:
    evidence = RuleEvidence(
        field="rest_days_away", op=RuleOp.LE, threshold=5, state=ScreenState.TRUE
    )
    _extra_rejected(
        LabelEvidence,
        {
            "game_id": "g1",
            "spec_id": "s1",
            "spec_version": 1,
            "state": ScreenState.TRUE,
            "labeler_version": "v1",
        },
    )
    _extra_rejected(
        LabeledGame,
        {
            "label_id": "l1",
            "game_id": "g1",
            "spec_id": "s1",
            "spec_version": 1,
            "label": 1,
            "evidence": [evidence.model_dump()],
            "labeler_version": "v1",
            "labeled_at": NOW,
        },
    )
    _extra_rejected(
        StatResult,
        {
            "stat_id": "st1",
            "spec_id": "s1",
            "spec_version": 1,
            "split": DatasetSplit.DEV,
            "n": 10,
            "positives": 4,
            "method": "bootstrap",
            "computed_at": NOW,
        },
    )


def test_label_and_stat_invariants() -> None:
    with pytest.raises(ValidationError, match="evaluable labels"):
        LabeledGame(
            label_id="l1",
            game_id="g1",
            spec_id="s1",
            spec_version=1,
            label=None,
            labeler_version="v1",
            labeled_at=NOW,
        )
    with pytest.raises(ValidationError, match="non-evaluable labels"):
        LabeledGame(
            label_id="l1",
            game_id="g1",
            spec_id="s1",
            spec_version=1,
            label=0,
            evaluable=False,
            labeler_version="v1",
            labeled_at=NOW,
        )
    with pytest.raises(ValidationError, match="positives cannot exceed n"):
        StatResult(
            stat_id="st1",
            spec_id="s1",
            spec_version=1,
            split=DatasetSplit.DEV,
            n=2,
            positives=3,
            method="bootstrap",
            computed_at=NOW,
        )


def test_research_contracts_reject_extra_fields() -> None:
    spec = demo_specs()[0]
    _extra_rejected(
        ResearchBrief,
        {
            "candidate_key": "short-rest",
            "title": "Short rest",
            "definition": "Away team on short rest.",
            "query": "Does short rest matter?",
        },
    )
    _extra_rejected(
        ResearchReport,
        {
            "report_id": "r1",
            "candidate_key": spec.candidate_key,
            "provider": "seeded_literature",
            "title": spec.title,
            "summary": spec.rationale,
            "proposed_rule": spec.rule.model_dump(),
            "required_fields": spec.required_fields,
            "citations": [CITATION.model_dump()],
            "created_at": NOW,
        },
    )
    _extra_rejected(
        SpecPromotion,
        {
            "spec_id": spec.spec_id,
            "version": 1,
            "status": PreconditionStatus.PROVISIONAL,
            "reason": "pending",
            "decided_at": NOW,
        },
    )
    _extra_rejected(
        ValidatedPrecondition,
        {
            "spec_id": spec.spec_id,
            "spec_version": 1,
            "status": PreconditionStatus.PROVISIONAL,
            "valid_from": NOW,
            "reason": "pending",
            "updated_at": NOW,
        },
    )


def test_research_report_schema_gate() -> None:
    base = {
        "report_id": "r1",
        "candidate_key": "short-rest",
        "provider": "seeded_literature",
        "title": "Short rest",
        "summary": "Short rest increases upset risk.",
        "created_at": NOW,
    }
    with pytest.raises(ValidationError, match="rule or a rejection_reason"):
        ResearchReport(**base)
    with pytest.raises(ValidationError, match="required_fields must include"):
        ResearchReport(
            **base,
            proposed_rule=RuleSpec(field="rest_days_away", op=RuleOp.LE, value=5),
            required_fields=["travel_km_away"],
            citations=[CITATION],
        )
    with pytest.raises(ValidationError, match="at least one citation"):
        ResearchReport(
            **base,
            proposed_rule=RuleSpec(field="rest_days_away", op=RuleOp.LE, value=5),
            required_fields=["rest_days_away"],
        )
    rejected = ResearchReport(**base, rejection_reason="not operationalizable")
    assert rejected.proposed_rule is None


def test_promotion_and_validation_require_citations() -> None:
    with pytest.raises(ValidationError, match="must carry a citation"):
        ValidatedPrecondition(
            spec_id="s1",
            spec_version=1,
            status=PreconditionStatus.VALIDATED,
            valid_from=NOW,
            reason="passed",
            updated_at=NOW,
        )


def test_tool_contracts_reject_extra_fields_and_bad_values() -> None:
    _extra_rejected(
        SearchHit,
        {
            "title": "Story",
            "url": "https://www.espn.com/story",
            "domain": "espn.com",
        },
    )
    _extra_rejected(
        FetchedPage,
        {
            "url": "https://www.espn.com/story",
            "domain": "espn.com",
            "text": "body",
            "fetched_at": NOW,
            "content_hash": "a" * 64,
        },
    )
    with pytest.raises(ValidationError, match="must start with http"):
        SearchHit(title="Bad", url="espn.com/story", domain="espn.com")
    with pytest.raises(ValidationError, match="at least 64 characters"):
        FetchedPage(
            url="https://www.espn.com/story",
            domain="espn.com",
            text="body",
            fetched_at=NOW,
            content_hash="short",
        )


def test_monitor_contracts_reject_extra_fields() -> None:
    game = demo_games()[0]
    spec = demo_specs()[0]
    evidence = RuleEvidence(
        field=spec.rule.field, op=spec.rule.op, threshold=spec.rule.value, state=ScreenState.TRUE
    )
    matched = {
        "spec_id": spec.spec_id,
        "version": 1,
        "title": spec.title,
        "evidence": evidence.model_dump(),
    }
    decision = MonitorDecision(
        game_id=game.game_id,
        decision=MonitorDecisionType.CONFIRMED,
        rationale="Short rest and travel align.",
        evidence_ids=["ev-1"],
        created_at=NOW,
    )
    _extra_rejected(
        ConfirmedFlag,
        {
            "game_id": game.game_id,
            "matched_specs": [matched],
            "rationale": "Confirmed.",
            "evidence_ids": ["ev-1"],
            "decision": decision.model_dump(),
            "confirmed_at": NOW,
        },
    )
    with pytest.raises(ValidationError, match="requires a confirmed decision"):
        ConfirmedFlag(
            game_id=game.game_id,
            matched_specs=[matched],
            rationale="Wrong.",
            evidence_ids=["ev-1"],
            decision=decision.model_copy(update={"decision": MonitorDecisionType.CONTRADICTED}),
            confirmed_at=NOW,
        )


def test_enums_and_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RuleEvidence(field="x", op="greater", state=ScreenState.TRUE)
    with pytest.raises(ValidationError, match="timezone-aware"):
        SearchHit(
            title="Story",
            url="https://www.espn.com/story",
            domain="espn.com",
            published_at=datetime(2026, 11, 22, 12, 0),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        SpecPromotion(
            spec_id="s1",
            version=1,
            status=PreconditionStatus.PROVISIONAL,
            reason="pending",
            decided_at=datetime(2026, 11, 22, 12, 0),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        HistoricalGameRecord(
            game_id="g1",
            season=2025,
            kickoff_utc=datetime(2025, 11, 22, 12, 0),
            home=TEAM_HOME,
            away=TEAM_AWAY,
            fetched_at=NOW,
        )
