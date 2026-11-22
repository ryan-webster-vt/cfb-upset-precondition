"""Typed repositories for every aggregate in the Phase 1 schema.

All SQL lives here (and in ``db.py``); agents and pipelines only see models or
small row dataclasses. JSON columns use canonical JSON so replaying the same
object produces byte-identical evidence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cfb_upset.contracts import (
    AgentEvent,
    CacheEntry,
    Citation,
    HistoricalGameRecord,
    LabelAudit,
    LabeledGame,
    PreconditionSpec,
    PreconditionStatus,
    QuarantineRecord,
    ResearchReport,
    RuleEvidence,
    RuleSpec,
    StatResult,
    TeamInfo,
    ValidatedPrecondition,
    VenueInfo,
)
from cfb_upset.ids import canonical_json
from cfb_upset.store.db import Database, parse_utc, utc_iso
from cfb_upset.store.evidence import EvidenceRecord

# ---------------------------------------------------------------------------
# Row-shaped dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredGame:
    """One ``games`` row, independent of the rich ingestion contract."""

    game_id: str
    season: int
    week: int | None
    season_type: int
    kickoff_utc: datetime
    home_team_id: str
    away_team_id: str
    neutral_site: bool
    conference_game: bool
    venue_id: str | None
    status: str
    home_score: int | None
    away_score: int | None
    winner_team_id: str | None
    is_fbs_vs_fbs: bool
    ingested_at: datetime
    source: str


@dataclass(frozen=True)
class StoredField:
    game_id: str
    field_name: str
    value: Any
    known_at_utc: datetime
    source: str
    source_url: str | None = None
    fetched_at_utc: datetime | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class StoredFeature:
    game_id: str
    feature_name: str
    value: float | None
    known_at_utc: datetime
    feature_version: str


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    slate_date: date
    game_ids: list[str]
    spec_set_hash: str
    config_hash: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    budget_seconds: float | None = None
    trace_path: str | None = None


@dataclass(frozen=True)
class EvidenceLink:
    evidence_id: str
    ref_type: str
    ref_id: str
    supports: bool
    quote: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def _row_bool(value: Any) -> bool:
    return bool(value)


def _row_optional_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _value_at(record: HistoricalGameRecord, field_name: str) -> Any:
    """Read a dotted field path from a record, returning ``_MISSING`` if absent."""

    dumped = record.model_dump(mode="json")
    current: Any = dumped
    for part in field_name.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


class _Missing:
    pass


_MISSING = _Missing()


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


class TeamsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(
        self,
        team: TeamInfo,
        *,
        venue_id: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        stamp = utc_iso(updated_at or self.database.clock.now())
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO teams (
                    team_id, school, nickname, conference_id, is_fbs, color,
                    alt_color, logo_url, venue_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET
                    school = excluded.school,
                    nickname = excluded.nickname,
                    conference_id = excluded.conference_id,
                    is_fbs = excluded.is_fbs,
                    color = excluded.color,
                    alt_color = excluded.alt_color,
                    logo_url = excluded.logo_url,
                    venue_id = COALESCE(excluded.venue_id, teams.venue_id),
                    updated_at = excluded.updated_at
                """,
                (
                    team.team_id,
                    team.school,
                    team.nickname,
                    team.conference,
                    int(team.is_fbs),
                    team.color,
                    team.alt_color,
                    team.logo_url,
                    venue_id,
                    stamp,
                ),
            )

    def get(self, team_id: str) -> TeamInfo | None:
        with self.database.session() as connection:
            row = connection.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, fbs_only: bool = False) -> list[TeamInfo]:
        sql = "SELECT * FROM teams"
        params: tuple[Any, ...] = ()
        if fbs_only:
            sql += " WHERE is_fbs = 1"
        sql += " ORDER BY school"
        with self.database.session() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM teams").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TeamInfo:
        return TeamInfo(
            team_id=row["team_id"],
            school=row["school"],
            nickname=row["nickname"],
            conference=row["conference_id"],
            is_fbs=_row_bool(row["is_fbs"]),
            color=row["color"],
            alt_color=row["alt_color"],
            logo_url=row["logo_url"],
        )


class VenuesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, venue: VenueInfo) -> str:
        if not venue.venue_id:
            raise ValueError("a persisted venue requires venue_id")
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO venues (
                    venue_id, name, city, state, country, indoor, grass,
                    lat, lon, altitude_m, tz, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue_id) DO UPDATE SET
                    name = excluded.name,
                    city = COALESCE(excluded.city, venues.city),
                    state = COALESCE(excluded.state, venues.state),
                    country = COALESCE(excluded.country, venues.country),
                    indoor = COALESCE(excluded.indoor, venues.indoor),
                    grass = COALESCE(excluded.grass, venues.grass),
                    lat = COALESCE(excluded.lat, venues.lat),
                    lon = COALESCE(excluded.lon, venues.lon),
                    altitude_m = COALESCE(excluded.altitude_m, venues.altitude_m),
                    tz = COALESCE(excluded.tz, venues.tz),
                    source = excluded.source
                """,
                (
                    venue.venue_id,
                    venue.name,
                    venue.city,
                    venue.state,
                    venue.country,
                    None if venue.indoor is None else int(venue.indoor),
                    None if venue.grass is None else int(venue.grass),
                    venue.lat,
                    venue.lon,
                    venue.altitude_m,
                    venue.tz,
                    venue.source,
                ),
            )
        return venue.venue_id

    def get(self, venue_id: str) -> VenueInfo | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM venues WHERE venue_id = ?", (venue_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self) -> list[VenueInfo]:
        with self.database.session() as connection:
            rows = connection.execute("SELECT * FROM venues ORDER BY name").fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM venues").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> VenueInfo:
        return VenueInfo(
            venue_id=row["venue_id"],
            name=row["name"],
            city=row["city"],
            state=row["state"],
            country=row["country"],
            indoor=_row_optional_bool(row["indoor"]),
            grass=_row_optional_bool(row["grass"]),
            lat=row["lat"],
            lon=row["lon"],
            altitude_m=row["altitude_m"],
            tz=row["tz"],
            source=row["source"],
        )


class GameFieldsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, field: StoredField) -> None:
        with self.database.session() as connection:
            self._record(connection, field)

    def record_many(self, fields: list[StoredField]) -> None:
        with self.database.session() as connection:
            for field in fields:
                self._record(connection, field)

    @staticmethod
    def _record(connection: sqlite3.Connection, field: StoredField) -> None:
        connection.execute(
            """
            INSERT INTO game_fields (
                game_id, field_name, value_json, known_at_utc, source,
                source_url, fetched_at_utc, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, field_name, source) DO UPDATE SET
                value_json = excluded.value_json,
                known_at_utc = excluded.known_at_utc,
                source_url = excluded.source_url,
                fetched_at_utc = excluded.fetched_at_utc,
                confidence = excluded.confidence
            """,
            (
                field.game_id,
                field.field_name,
                canonical_json(field.value),
                utc_iso(field.known_at_utc),
                field.source,
                field.source_url,
                utc_iso(field.fetched_at_utc) if field.fetched_at_utc else None,
                field.confidence,
            ),
        )

    def get(self, game_id: str) -> dict[str, StoredField]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM game_fields WHERE game_id = ? ORDER BY field_name, source",
                (game_id,),
            ).fetchall()
        return {row["field_name"]: self._from_row(row) for row in rows}

    def value(self, game_id: str, field_name: str) -> Any:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT * FROM game_fields
                WHERE game_id = ? AND field_name = ?
                ORDER BY source LIMIT 1
                """,
                (game_id, field_name),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM game_fields").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredField:
        return StoredField(
            game_id=row["game_id"],
            field_name=row["field_name"],
            value=json.loads(row["value_json"]),
            known_at_utc=parse_utc(row["known_at_utc"]),
            source=row["source"],
            source_url=row["source_url"],
            fetched_at_utc=parse_utc(row["fetched_at_utc"]),
            confidence=row["confidence"],
        )


class GameFeaturesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, feature: StoredFeature) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO game_features (
                    game_id, feature_name, value, known_at_utc, feature_version
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(game_id, feature_name, feature_version) DO UPDATE SET
                    value = excluded.value,
                    known_at_utc = excluded.known_at_utc
                """,
                (
                    feature.game_id,
                    feature.feature_name,
                    feature.value,
                    utc_iso(feature.known_at_utc),
                    feature.feature_version,
                ),
            )

    def get(self, game_id: str, feature_version: str | None = None) -> dict[str, StoredFeature]:
        sql = "SELECT * FROM game_features WHERE game_id = ?"
        params: list[Any] = [game_id]
        if feature_version is not None:
            sql += " AND feature_version = ?"
            params.append(feature_version)
        sql += " ORDER BY feature_name"
        with self.database.session() as connection:
            rows = connection.execute(sql, params).fetchall()
        return {row["feature_name"]: self._from_row(row) for row in rows}

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM game_features").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredFeature:
        return StoredFeature(
            game_id=row["game_id"],
            feature_name=row["feature_name"],
            value=row["value"],
            known_at_utc=parse_utc(row["known_at_utc"]),
            feature_version=row["feature_version"],
        )


class GamesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.fields = GameFieldsRepository(database)

    def upsert(self, record: HistoricalGameRecord) -> None:
        # Keep identity/venue tables populated even when a caller only hands us
        # a game record; Phase 2's orchestrator may also seed them explicitly.
        teams = TeamsRepository(self.database)
        teams.upsert(record.home)
        teams.upsert(record.away)
        if record.venue is not None and record.venue.venue_id:
            VenuesRepository(self.database).upsert(record.venue)
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO games (
                    game_id, season, week, season_type, kickoff_utc, home_team_id,
                    away_team_id, neutral_site, conference_game, venue_id, status,
                    home_score, away_score, winner_team_id, is_fbs_vs_fbs,
                    ingested_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    season = excluded.season,
                    week = excluded.week,
                    season_type = excluded.season_type,
                    kickoff_utc = excluded.kickoff_utc,
                    home_team_id = excluded.home_team_id,
                    away_team_id = excluded.away_team_id,
                    neutral_site = excluded.neutral_site,
                    conference_game = excluded.conference_game,
                    venue_id = excluded.venue_id,
                    status = excluded.status,
                    home_score = excluded.home_score,
                    away_score = excluded.away_score,
                    winner_team_id = excluded.winner_team_id,
                    is_fbs_vs_fbs = excluded.is_fbs_vs_fbs,
                    ingested_at = excluded.ingested_at,
                    source = excluded.source
                """,
                (
                    record.game_id,
                    record.season,
                    record.week,
                    record.season_type,
                    utc_iso(record.kickoff_utc),
                    record.home.team_id,
                    record.away.team_id,
                    int(record.neutral_site),
                    int(record.conference_game),
                    record.venue.venue_id if record.venue else None,
                    record.status.value,
                    record.home_score,
                    record.away_score,
                    record.winner_team_id,
                    int(record.is_fbs_vs_fbs),
                    utc_iso(record.fetched_at),
                    record.source,
                ),
            )
            for field_name, provenance in record.field_provenance.items():
                value = _value_at(record, field_name)
                if value is _MISSING:
                    continue
                self.fields._record(
                    connection,
                    StoredField(
                        game_id=record.game_id,
                        field_name=field_name,
                        value=value,
                        known_at_utc=provenance.known_at,
                        source=provenance.source,
                        source_url=provenance.source_url,
                        fetched_at_utc=provenance.fetched_at or record.fetched_at,
                        confidence=provenance.confidence,
                    ),
                )

    def get(self, game_id: str) -> StoredGame | None:
        with self.database.session() as connection:
            row = connection.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        season: int | None = None,
        week: int | None = None,
        fbs_only: bool = False,
    ) -> list[StoredGame]:
        clauses: list[str] = []
        params: list[Any] = []
        if season is not None:
            clauses.append("season = ?")
            params.append(season)
        if week is not None:
            clauses.append("week = ?")
            params.append(week)
        if fbs_only:
            clauses.append("is_fbs_vs_fbs = 1")
        sql = "SELECT * FROM games"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY kickoff_utc, game_id"
        with self.database.session() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM games").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredGame:
        return StoredGame(
            game_id=row["game_id"],
            season=row["season"],
            week=row["week"],
            season_type=row["season_type"],
            kickoff_utc=parse_utc(row["kickoff_utc"]),
            home_team_id=row["home_team_id"],
            away_team_id=row["away_team_id"],
            neutral_site=_row_bool(row["neutral_site"]),
            conference_game=_row_bool(row["conference_game"]),
            venue_id=row["venue_id"],
            status=row["status"],
            home_score=row["home_score"],
            away_score=row["away_score"],
            winner_team_id=row["winner_team_id"],
            is_fbs_vs_fbs=_row_bool(row["is_fbs_vs_fbs"]),
            ingested_at=parse_utc(row["ingested_at"]),
            source=row["source"],
        )


class SpecsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(
        self,
        spec: PreconditionSpec,
        *,
        research_report: ResearchReport | None = None,
        rejection_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        stamp = utc_iso(created_at or spec.created_at or self.database.clock.now())
        report_json = (
            canonical_json(research_report.model_dump(mode="json"))
            if research_report is not None
            else None
        )
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO precondition_spec (
                    spec_id, version, candidate_key, title, rationale, research_report_json,
                    rule_json, required_fields_json, scope, min_support,
                    citations_json, source, created_at, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spec_id, version) DO UPDATE SET
                    candidate_key = excluded.candidate_key,
                    title = excluded.title,
                    rationale = excluded.rationale,
                    research_report_json = excluded.research_report_json,
                    rule_json = excluded.rule_json,
                    required_fields_json = excluded.required_fields_json,
                    scope = excluded.scope,
                    min_support = excluded.min_support,
                    citations_json = excluded.citations_json,
                    source = excluded.source,
                    rejection_reason = excluded.rejection_reason
                """,
                (
                    spec.spec_id,
                    spec.version,
                    spec.candidate_key,
                    spec.title,
                    spec.rationale,
                    report_json,
                    canonical_json(spec.rule.model_dump(mode="json")),
                    canonical_json(spec.required_fields),
                    spec.scope,
                    spec.min_support,
                    canonical_json([c.model_dump(mode="json") for c in spec.citations]),
                    spec.source,
                    stamp,
                    rejection_reason,
                ),
            )

    def get(self, spec_id: str, version: int) -> PreconditionSpec | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM precondition_spec WHERE spec_id = ? AND version = ?",
                (spec_id, version),
            ).fetchone()
            status = connection.execute(
                "SELECT status FROM validated_preconditions WHERE spec_id = ? AND spec_version = ?",
                (spec_id, version),
            ).fetchone()
        return self._from_row(row, status["status"] if status else None) if row else None

    def list(self, *, active_only: bool = False) -> list[PreconditionSpec]:
        if active_only:
            sql = """
                SELECT p.* FROM precondition_spec p
                JOIN spec_store s ON s.spec_id = p.spec_id AND s.version = p.version
                WHERE s.is_active = 1
                ORDER BY p.candidate_key, p.version
            """
        else:
            sql = "SELECT * FROM precondition_spec ORDER BY candidate_key, version"
        with self.database.session() as connection:
            rows = connection.execute(sql).fetchall()
        return [self._from_row(row, None) for row in rows]

    def activate(
        self,
        spec_id: str,
        version: int,
        *,
        is_active: bool = True,
        notes: str | None = None,
        promoted_at: datetime | None = None,
    ) -> None:
        stamp = utc_iso(promoted_at or self.database.clock.now())
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO spec_store (spec_id, version, is_active, promoted_at, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(spec_id, version) DO UPDATE SET
                    is_active = excluded.is_active,
                    promoted_at = COALESCE(excluded.promoted_at, spec_store.promoted_at),
                    notes = COALESCE(excluded.notes, spec_store.notes)
                """,
                (spec_id, version, int(is_active), stamp, notes),
            )

    def is_active(self, spec_id: str, version: int) -> bool:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT is_active FROM spec_store WHERE spec_id = ? AND version = ?",
                (spec_id, version),
            ).fetchone()
        return bool(row["is_active"]) if row else False

    def research_report(self, spec_id: str, version: int) -> ResearchReport | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT research_report_json FROM precondition_spec
                WHERE spec_id = ? AND version = ?
                """,
                (spec_id, version),
            ).fetchone()
        if not row or not row["research_report_json"]:
            return None
        return ResearchReport.model_validate(json.loads(row["research_report_json"]))

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM precondition_spec").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row, status: str | None) -> PreconditionSpec:
        return PreconditionSpec(
            spec_id=row["spec_id"],
            version=row["version"],
            candidate_key=row["candidate_key"],
            title=row["title"],
            rationale=row["rationale"] or row["title"],
            rule=RuleSpec.model_validate(json.loads(row["rule_json"])),
            required_fields=json.loads(row["required_fields_json"]),
            scope=row["scope"],
            min_support=row["min_support"],
            citations=[Citation.model_validate(item) for item in json.loads(row["citations_json"])],
            source=row["source"],
            status=PreconditionStatus(status) if status else PreconditionStatus.PROVISIONAL,
            created_at=parse_utc(row["created_at"]),
        )


class LabelsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, label: LabeledGame) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO labeled_games (
                    label_id, game_id, spec_id, spec_version, label, evaluable,
                    evidence_json, labeler_version, labeled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, spec_id, spec_version) DO UPDATE SET
                    label = excluded.label,
                    evaluable = excluded.evaluable,
                    evidence_json = excluded.evidence_json,
                    labeler_version = excluded.labeler_version,
                    labeled_at = excluded.labeled_at
                """,
                (
                    label.label_id,
                    label.game_id,
                    label.spec_id,
                    label.spec_version,
                    label.label,
                    int(label.evaluable),
                    canonical_json([item.model_dump(mode="json") for item in label.evidence]),
                    label.labeler_version,
                    utc_iso(label.labeled_at),
                ),
            )

    def get(self, label_id: str) -> LabeledGame | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM labeled_games WHERE label_id = ?", (label_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list_for_game(self, game_id: str) -> list[LabeledGame]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM labeled_games WHERE game_id = ? ORDER BY spec_id, spec_version",
                (game_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def save_audit(self, audit: LabelAudit) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO label_audits (
                    audit_id, spec_id, spec_version, game_id, sampled,
                    adjudication, evidence_ids_json, auditor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(audit_id) DO UPDATE SET
                    adjudication = excluded.adjudication,
                    evidence_ids_json = excluded.evidence_ids_json,
                    auditor = excluded.auditor
                """,
                (
                    audit.audit_id,
                    audit.spec_id,
                    audit.spec_version,
                    audit.game_id,
                    int(audit.sampled),
                    audit.adjudication.value,
                    canonical_json(audit.evidence_ids),
                    audit.auditor,
                    utc_iso(audit.created_at),
                ),
            )

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM labeled_games").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LabeledGame:
        return LabeledGame(
            label_id=row["label_id"],
            game_id=row["game_id"],
            spec_id=row["spec_id"],
            spec_version=row["spec_version"],
            label=row["label"],
            evaluable=_row_bool(row["evaluable"]),
            evidence=[
                RuleEvidence.model_validate(item) for item in json.loads(row["evidence_json"])
            ],
            labeler_version=row["labeler_version"],
            labeled_at=parse_utc(row["labeled_at"]),
        )


class StatsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_stat(self, result: StatResult) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO stat_results (
                    stat_id, spec_id, spec_version, split, n, positives, risk_diff,
                    ci_low, ci_high, odds_ratio, p_value, q_value, method,
                    diagnostics_json, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stat_id) DO UPDATE SET
                    n = excluded.n,
                    positives = excluded.positives,
                    risk_diff = excluded.risk_diff,
                    ci_low = excluded.ci_low,
                    ci_high = excluded.ci_high,
                    odds_ratio = excluded.odds_ratio,
                    p_value = excluded.p_value,
                    q_value = excluded.q_value,
                    method = excluded.method,
                    diagnostics_json = excluded.diagnostics_json,
                    computed_at = excluded.computed_at
                """,
                (
                    result.stat_id,
                    result.spec_id,
                    result.spec_version,
                    result.split.value,
                    result.n,
                    result.positives,
                    result.risk_diff,
                    result.ci_low,
                    result.ci_high,
                    result.odds_ratio,
                    result.p_value,
                    result.q_value,
                    result.method,
                    canonical_json(result.diagnostics),
                    utc_iso(result.computed_at),
                ),
            )

    def list_stats(self, spec_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM stat_results"
        params: tuple[Any, ...] = ()
        if spec_id is not None:
            sql += " WHERE spec_id = ?"
            params = (spec_id,)
        sql += " ORDER BY spec_id, spec_version, split"
        with self.database.session() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def save_validated(self, precondition: ValidatedPrecondition) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO validated_preconditions (
                    spec_id, spec_version, status, acceptance_json, effect_json,
                    citations_json, valid_from, reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spec_id) DO UPDATE SET
                    spec_version = excluded.spec_version,
                    status = excluded.status,
                    acceptance_json = excluded.acceptance_json,
                    effect_json = excluded.effect_json,
                    citations_json = excluded.citations_json,
                    valid_from = excluded.valid_from,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    precondition.spec_id,
                    precondition.spec_version,
                    precondition.status.value,
                    canonical_json(precondition.acceptance),
                    canonical_json(precondition.effect),
                    canonical_json(
                        [citation.model_dump(mode="json") for citation in precondition.citations]
                    ),
                    utc_iso(precondition.valid_from),
                    precondition.reason,
                    utc_iso(precondition.updated_at),
                ),
            )

    def get_validated(self, spec_id: str) -> ValidatedPrecondition | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM validated_preconditions WHERE spec_id = ?", (spec_id,)
            ).fetchone()
        return self._validated_from_row(row) if row else None

    def list_validated(self, status: str | None = None) -> list[ValidatedPrecondition]:
        sql = "SELECT * FROM validated_preconditions"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY spec_id"
        with self.database.session() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._validated_from_row(row) for row in rows]

    @staticmethod
    def _validated_from_row(row: sqlite3.Row) -> ValidatedPrecondition:
        return ValidatedPrecondition(
            spec_id=row["spec_id"],
            spec_version=row["spec_version"],
            status=PreconditionStatus(row["status"]),
            acceptance=json.loads(row["acceptance_json"]),
            effect=json.loads(row["effect_json"]),
            citations=[Citation.model_validate(item) for item in json.loads(row["citations_json"])],
            valid_from=parse_utc(row["valid_from"]),
            reason=row["reason"],
            updated_at=parse_utc(row["updated_at"]),
        )


class EvidenceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, record: EvidenceRecord) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id, source_url, domain, title, published_at, fetched_at,
                    content_hash, snapshot_path, kind, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    domain = excluded.domain,
                    title = excluded.title,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at,
                    content_hash = excluded.content_hash,
                    snapshot_path = excluded.snapshot_path,
                    kind = excluded.kind
                """,
                (
                    record.evidence_id,
                    record.source_url,
                    record.domain,
                    record.title,
                    utc_iso(record.published_at) if record.published_at else None,
                    utc_iso(record.fetched_at),
                    record.content_hash,
                    record.snapshot_path,
                    record.kind,
                    utc_iso(record.created_at),
                ),
            )

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def find_by_hash(self, content_hash: str) -> EvidenceRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM evidence WHERE content_hash = ? ORDER BY created_at LIMIT 1",
                (content_hash,),
            ).fetchone()
        return self._from_row(row) if row else None

    def link(
        self,
        evidence_id: str,
        *,
        ref_type: str,
        ref_id: str,
        supports: bool = True,
        quote: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        stamp = utc_iso(created_at or self.database.clock.now())
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO evidence_links (
                    evidence_id, ref_type, ref_id, supports, quote, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id, ref_type, ref_id) DO UPDATE SET
                    supports = excluded.supports,
                    quote = excluded.quote
                """,
                (evidence_id, ref_type, ref_id, int(supports), quote, stamp),
            )

    def links_for(self, ref_type: str, ref_id: str) -> list[EvidenceLink]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_links
                WHERE ref_type = ? AND ref_id = ? ORDER BY created_at
                """,
                (ref_type, ref_id),
            ).fetchall()
        return [
            EvidenceLink(
                evidence_id=row["evidence_id"],
                ref_type=row["ref_type"],
                ref_id=row["ref_id"],
                supports=_row_bool(row["supports"]),
                quote=row["quote"],
                created_at=parse_utc(row["created_at"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            source_url=row["source_url"],
            domain=row["domain"],
            title=row["title"],
            published_at=parse_utc(row["published_at"]),
            fetched_at=parse_utc(row["fetched_at"]),
            content_hash=row["content_hash"],
            snapshot_path=row["snapshot_path"],
            kind=row["kind"],
            created_at=parse_utc(row["created_at"]),
        )


class RunsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_run(self, run: AnalysisRun) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    run_id, slate_date, games_json, spec_set_hash, config_hash,
                    status, started_at, finished_at, budget_seconds, trace_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    slate_date = excluded.slate_date,
                    games_json = excluded.games_json,
                    spec_set_hash = excluded.spec_set_hash,
                    config_hash = excluded.config_hash,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    budget_seconds = excluded.budget_seconds,
                    trace_path = excluded.trace_path
                """,
                (
                    run.run_id,
                    run.slate_date.isoformat(),
                    canonical_json(run.game_ids),
                    run.spec_set_hash,
                    run.config_hash,
                    run.status,
                    utc_iso(run.started_at),
                    utc_iso(run.finished_at) if run.finished_at else None,
                    run.budget_seconds,
                    run.trace_path,
                ),
            )

    def get_run(self, run_id: str) -> AnalysisRun | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        return AnalysisRun(
            run_id=row["run_id"],
            slate_date=date.fromisoformat(row["slate_date"]),
            game_ids=json.loads(row["games_json"]),
            spec_set_hash=row["spec_set_hash"],
            config_hash=row["config_hash"],
            status=row["status"],
            started_at=parse_utc(row["started_at"]),
            finished_at=parse_utc(row["finished_at"]),
            budget_seconds=row["budget_seconds"],
            trace_path=row["trace_path"],
        )

    def save_cache(self, entry: CacheEntry) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO analysis_cache (
                    cache_key, game_id, spec_set_hash, evidence_hash,
                    scorer_version, embedding_version, result_json, created_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    result_json = excluded.result_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    entry.cache_key,
                    entry.game_id,
                    entry.spec_set_hash,
                    entry.evidence_hash,
                    entry.scorer_version,
                    entry.embedding_version,
                    canonical_json(entry.result_json),
                    utc_iso(entry.created_at),
                    utc_iso(entry.expires_at) if entry.expires_at else None,
                ),
            )

    def get_cache(self, cache_key: str) -> CacheEntry | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if not row:
            return None
        return CacheEntry(
            cache_key=row["cache_key"],
            game_id=row["game_id"],
            spec_set_hash=row["spec_set_hash"],
            evidence_hash=row["evidence_hash"],
            scorer_version=row["scorer_version"],
            embedding_version=row["embedding_version"],
            result_json=json.loads(row["result_json"]),
            created_at=parse_utc(row["created_at"]),
            expires_at=parse_utc(row["expires_at"]),
        )


class EventsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, event: AgentEvent) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO agent_events (
                    event_id, run_id, agent, phase, event_type, payload_json, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.agent,
                    event.phase,
                    event.event_type,
                    canonical_json(event.payload),
                    utc_iso(event.ts),
                ),
            )

    def list_for_run(self, run_id: str) -> list[AgentEvent]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_events WHERE run_id = ? ORDER BY ts, event_id", (run_id,)
            ).fetchall()
        return [
            AgentEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                agent=row["agent"],
                phase=row["phase"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                ts=parse_utc(row["ts"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0])


class QuarantineRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, record: QuarantineRecord) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO quarantine (record_id, payload_json, errors_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    errors_json = excluded.errors_json
                """,
                (
                    record.record_id,
                    canonical_json(record.payload),
                    canonical_json(record.errors),
                    utc_iso(record.created_at),
                ),
            )

    def list(self, limit: int = 100) -> list[QuarantineRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM quarantine ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            QuarantineRecord(
                record_id=row["record_id"],
                payload=json.loads(row["payload_json"]),
                errors=json.loads(row["errors_json"]),
                created_at=parse_utc(row["created_at"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self.database.session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0])


class Repositories:
    """Facade exposing one repository per aggregate."""

    def __init__(self, database: Database | str | Path | None = None) -> None:
        if isinstance(database, (str, Path)) or database is None:
            database = Database(database)
        self.database = database
        self.teams = TeamsRepository(database)
        self.venues = VenuesRepository(database)
        self.games = GamesRepository(database)
        self.game_fields = GameFieldsRepository(database)
        self.game_features = GameFeaturesRepository(database)
        self.specs = SpecsRepository(database)
        self.labels = LabelsRepository(database)
        self.stats = StatsRepository(database)
        self.evidence = EvidenceRepository(database)
        self.runs = RunsRepository(database)
        self.events = EventsRepository(database)
        self.quarantine = QuarantineRepository(database)


__all__ = [
    "AnalysisRun",
    "EvidenceLink",
    "Repositories",
    "StoredFeature",
    "StoredField",
    "StoredGame",
]
