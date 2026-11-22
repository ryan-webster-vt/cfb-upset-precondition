"""Repository round-trips for every aggregate in the Phase 1 schema."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.contracts import (
    Adjudication,
    AgentEvent,
    CacheEntry,
    DatasetSplit,
    LabelAudit,
    LabeledGame,
    PreconditionStatus,
    QuarantineRecord,
    ResearchReport,
    RuleEvidence,
    RuleOp,
    ScreenState,
    StatResult,
    ValidatedPrecondition,
)
from cfb_upset.domain.leakage import is_admitted
from cfb_upset.fixtures.demo import demo_specs
from cfb_upset.store.db import Database
from cfb_upset.store.repositories import (
    AnalysisRun,
    Repositories,
    StoredFeature,
    StoredField,
)
from cfb_upset.store.seed import seed_all, seed_venues

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def repos(tmp_path: Path) -> Repositories:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    return Repositories(database)


def test_seed_teams_and_venues(repos: Repositories) -> None:
    counts = seed_all(repos)
    assert counts == {"teams": 13, "venues": 12}
    assert repos.teams.count() == 13
    assert repos.venues.count() == 12
    ohio = repos.teams.get("194")
    assert ohio is not None and ohio.school == "Ohio State"
    venue = repos.venues.get("5938")
    assert venue is not None
    assert venue.lat == pytest.approx(34.1861922)
    assert venue.altitude_m == pytest.approx(1158.0)
    assert venue.tz == "America/Denver"


def test_cfbd_venue_fields_fill_from_checked_in_fallback(repos: Repositories) -> None:
    payload = json.loads((FIXTURES / "cfbd" / "venues.json").read_text())
    from cfb_upset.adapters.cfbd import CfbdAdapter

    live = CfbdAdapter.parse_venues(payload)
    seed_venues(repos, cfbd_venues=live)
    # 11591 has no lat/lon/elevation/tz in the CFBD sample.
    venue = repos.venues.get("11591")
    assert venue is not None
    assert venue.lat == pytest.approx(46.9233)
    assert venue.altitude_m == pytest.approx(371.0)
    assert venue.tz == "America/Chicago"
    # 218 has an elevation string in CFBD and must be converted to a float.
    fiu = repos.venues.get("218")
    assert fiu is not None and fiu.altitude_m == pytest.approx(1.718581796)


def test_game_upsert_writes_identity_and_field_provenance(repos: Repositories) -> None:
    payload = json.loads((FIXTURES / "espn" / "scoreboard_20251115.json").read_text())
    record = EspnAdapter(FixtureTransport()).parse_scoreboard(payload, fetched_at=NOW)[0]
    repos.games.upsert(record)

    stored = repos.games.get(record.game_id)
    assert stored is not None
    assert stored.home_team_id == "194"
    assert stored.away_team_id == "26"
    assert stored.home_score == 48
    assert stored.away_score == 10
    assert stored.status == "final"
    assert repos.teams.get("194") is not None
    assert repos.venues.get("3861") is not None

    fields = repos.game_fields.get(record.game_id)
    assert {"home", "away", "kickoff_utc", "home_score", "venue"} <= set(fields)
    assert fields["home"].source == "espn"
    assert is_admitted("home", fields["home"].known_at_utc, record.kickoff_utc)
    assert not is_admitted("home_score", fields["home_score"].known_at_utc, record.kickoff_utc)


def test_game_count_and_season_filter(repos: Repositories) -> None:
    payload = json.loads((FIXTURES / "espn" / "scoreboard_20251115.json").read_text())
    records = EspnAdapter(FixtureTransport()).parse_scoreboard(payload, fetched_at=NOW)
    for record in records:
        repos.games.upsert(record)
    assert repos.games.count() == len(records)
    assert len(repos.games.list(season=2025, fbs_only=True)) == len(records)
    assert repos.games.list(season=2024) == []


def test_game_fields_and_features_direct_round_trip(repos: Repositories) -> None:
    repos.game_fields.record(
        StoredField(
            game_id="g1",
            field_name="rest_days_away",
            value=4,
            known_at_utc=NOW - timedelta(days=1),
            source="computed",
        )
    )
    assert repos.game_fields.value("g1", "rest_days_away") == 4
    repos.game_features.record(
        StoredFeature(
            game_id="g1",
            feature_name="rest_diff",
            value=-2.0,
            known_at_utc=NOW - timedelta(days=1),
            feature_version="v1",
        )
    )
    features = repos.game_features.get("g1", "v1")
    assert features["rest_diff"].value == pytest.approx(-2.0)


def test_spec_save_get_and_activate(repos: Repositories) -> None:
    spec = demo_specs()[0]
    report = ResearchReport(
        report_id="report-1",
        candidate_key=spec.candidate_key,
        provider="seeded_literature",
        title=spec.title,
        summary=spec.rationale,
        proposed_rule=spec.rule,
        required_fields=spec.required_fields,
        citations=spec.citations,
        created_at=NOW,
    )
    repos.specs.save(spec, research_report=report)
    loaded = repos.specs.get(spec.spec_id, spec.version)
    assert loaded is not None
    assert loaded.title == spec.title
    assert loaded.rule.op is spec.rule.op
    assert loaded.required_fields == spec.required_fields
    assert loaded.citations[0].title == spec.citations[0].title
    assert repos.specs.research_report(spec.spec_id, spec.version) is not None

    assert not repos.specs.is_active(spec.spec_id, spec.version)
    repos.specs.activate(spec.spec_id, spec.version, notes="approved for P1 test")
    assert repos.specs.is_active(spec.spec_id, spec.version)
    assert [item.spec_id for item in repos.specs.list(active_only=True)] == [spec.spec_id]


def test_labels_audits_stats_and_promotions(repos: Repositories) -> None:
    spec = demo_specs()[0]
    repos.specs.save(spec)
    evidence = RuleEvidence(
        field=spec.rule.field,
        op=RuleOp.LE,
        threshold=5,
        observed=4,
        state=ScreenState.TRUE,
        known_at=NOW - timedelta(days=1),
    )
    label = LabeledGame(
        label_id="label-1",
        game_id="g1",
        spec_id=spec.spec_id,
        spec_version=spec.version,
        label=1,
        evaluable=True,
        evidence=[evidence],
        labeler_version="v1",
        labeled_at=NOW,
    )
    repos.labels.save(label)
    loaded = repos.labels.get("label-1")
    assert loaded is not None and loaded.label == 1
    assert loaded.evidence[0].observed == 4
    assert repos.labels.list_for_game("g1")[0].spec_id == spec.spec_id

    audit = LabelAudit(
        audit_id="audit-1",
        spec_id=spec.spec_id,
        spec_version=spec.version,
        game_id="g1",
        adjudication=Adjudication.HOLD,
        evidence_ids=["ev-1"],
        auditor="reviewer",
        created_at=NOW,
    )
    repos.labels.save_audit(audit)

    stat = StatResult(
        stat_id="stat-1",
        spec_id=spec.spec_id,
        spec_version=spec.version,
        split=DatasetSplit.DEV,
        n=100,
        positives=30,
        risk_diff=0.12,
        p_value=0.01,
        q_value=0.04,
        method="cluster_bootstrap",
        computed_at=NOW,
    )
    repos.stats.save_stat(stat)
    assert repos.stats.list_stats(spec.spec_id)[0]["stat_id"] == "stat-1"

    validated = ValidatedPrecondition(
        spec_id=spec.spec_id,
        spec_version=spec.version,
        status=PreconditionStatus.VALIDATED,
        acceptance={"precision": 0.82},
        effect={"risk_diff": 0.12},
        citations=spec.citations,
        valid_from=NOW,
        reason="passed FDR and audit",
        updated_at=NOW,
    )
    repos.stats.save_validated(validated)
    loaded_validated = repos.stats.get_validated(spec.spec_id)
    assert loaded_validated is not None
    assert loaded_validated.status is PreconditionStatus.VALIDATED
    # The spec status is now read from validated_preconditions.
    assert repos.specs.get(spec.spec_id, spec.version).status is PreconditionStatus.VALIDATED


def test_evidence_record_and_links(repos: Repositories, tmp_path: Path) -> None:
    from cfb_upset.store.evidence import EvidenceStore

    store = EvidenceStore(tmp_path / "evidence")
    snapshot = store.write("citation body", kind="article")
    record = snapshot.to_record(
        source_url="https://www.espn.com/story",
        domain="espn.com",
        title="Story",
        published_at=NOW - timedelta(days=2),
        created_at=NOW,
    )
    repos.evidence.save(record)
    loaded = repos.evidence.get(record.evidence_id)
    assert loaded is not None and loaded.content_hash == record.content_hash
    assert repos.evidence.find_by_hash(record.content_hash).evidence_id == record.evidence_id
    repos.evidence.link(
        record.evidence_id,
        ref_type="spec",
        ref_id="spec-1",
        quote="short rest matters",
        created_at=NOW,
    )
    links = repos.evidence.links_for("spec", "spec-1")
    assert links[0].quote == "short rest matters"
    assert links[0].supports is True


def test_runs_cache_events_and_quarantine(repos: Repositories) -> None:
    run = AnalysisRun(
        run_id="run-1",
        slate_date=date(2026, 11, 28),
        game_ids=["g1", "g2"],
        spec_set_hash="spec-hash",
        config_hash="config-hash",
        status="completed",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=5),
        budget_seconds=300,
        trace_path="data/traces/run-1.jsonl",
    )
    repos.runs.save_run(run)
    loaded = repos.runs.get_run("run-1")
    assert loaded is not None and loaded.game_ids == ["g1", "g2"]
    assert loaded.slate_date == date(2026, 11, 28)

    entry = CacheEntry(
        cache_key="cache-1",
        game_id="g1",
        spec_set_hash="spec-hash",
        evidence_hash="evidence-hash",
        scorer_version="v1",
        embedding_version="ollama-4096",
        result_json={"probability": 0.3},
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    repos.runs.save_cache(entry)
    assert repos.runs.get_cache("cache-1").result_json == {"probability": 0.3}

    event = AgentEvent(
        event_id="event-1",
        run_id="run-1",
        agent="Upset-Scorer",
        phase="score",
        event_type="scored",
        payload={"alerts": 2},
        ts=NOW,
    )
    repos.events.append(event)
    assert [item.event_id for item in repos.events.list_for_run("run-1")] == ["event-1"]

    quarantine = QuarantineRecord(
        record_id="bad-1",
        payload={"game_id": "bad"},
        errors=["missing kickoff"],
        created_at=NOW,
    )
    repos.quarantine.add(quarantine)
    assert repos.quarantine.list()[0].errors == ["missing kickoff"]
