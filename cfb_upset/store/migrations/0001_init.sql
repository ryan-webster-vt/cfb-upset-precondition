-- Phase 1 schema. Keep this file additive and append-only: a later phase adds
-- 0002_*.sql rather than editing an already-applied migration.

CREATE TABLE IF NOT EXISTS teams (
    team_id       TEXT PRIMARY KEY,
    school        TEXT NOT NULL,
    nickname      TEXT,
    conference_id TEXT,
    is_fbs        INTEGER NOT NULL DEFAULT 1 CHECK (is_fbs IN (0, 1)),
    color         TEXT,
    alt_color     TEXT,
    logo_url      TEXT,
    venue_id      TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    city       TEXT,
    state      TEXT,
    country    TEXT,
    indoor     INTEGER CHECK (indoor IN (0, 1)),
    grass      INTEGER CHECK (grass IN (0, 1)),
    lat        REAL CHECK (lat IS NULL OR (lat >= -90.0 AND lat <= 90.0)),
    lon        REAL CHECK (lon IS NULL OR (lon >= -180.0 AND lon <= 180.0)),
    altitude_m REAL,
    tz         TEXT,
    source     TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    season         INTEGER NOT NULL,
    week           INTEGER,
    season_type    INTEGER NOT NULL DEFAULT 2,
    kickoff_utc    TEXT NOT NULL,
    home_team_id   TEXT NOT NULL,
    away_team_id   TEXT NOT NULL,
    neutral_site   INTEGER NOT NULL DEFAULT 0 CHECK (neutral_site IN (0, 1)),
    conference_game INTEGER NOT NULL DEFAULT 0 CHECK (conference_game IN (0, 1)),
    venue_id       TEXT,
    status         TEXT NOT NULL,
    home_score     INTEGER,
    away_score     INTEGER,
    winner_team_id TEXT,
    is_fbs_vs_fbs  INTEGER NOT NULL DEFAULT 1 CHECK (is_fbs_vs_fbs IN (0, 1)),
    ingested_at    TEXT NOT NULL,
    source         TEXT NOT NULL,
    CHECK (home_team_id <> away_team_id)
);

-- Per-field provenance. ``value_json`` is canonical JSON so a null, a number,
-- and the string "null" remain distinguishable.
CREATE TABLE IF NOT EXISTS game_fields (
    game_id       TEXT NOT NULL,
    field_name    TEXT NOT NULL,
    value_json    TEXT NOT NULL,
    known_at_utc  TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_url    TEXT,
    fetched_at_utc TEXT,
    confidence    REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    PRIMARY KEY (game_id, field_name, source)
);

CREATE TABLE IF NOT EXISTS game_features (
    game_id         TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    value           REAL,
    known_at_utc    TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    PRIMARY KEY (game_id, feature_name, feature_version)
);

CREATE TABLE IF NOT EXISTS precondition_spec (
    spec_id              TEXT NOT NULL,
    version              INTEGER NOT NULL CHECK (version >= 1),
    candidate_key        TEXT NOT NULL,
    title                TEXT NOT NULL,
    rationale            TEXT NOT NULL DEFAULT '',
    research_report_json TEXT,
    rule_json            TEXT NOT NULL,
    required_fields_json TEXT NOT NULL,
    scope                TEXT NOT NULL,
    min_support          INTEGER NOT NULL DEFAULT 0 CHECK (min_support >= 0),
    citations_json       TEXT NOT NULL,
    source               TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    rejection_reason     TEXT,
    PRIMARY KEY (spec_id, version)
);

CREATE TABLE IF NOT EXISTS spec_store (
    spec_id     TEXT NOT NULL,
    version     INTEGER NOT NULL CHECK (version >= 1),
    is_active   INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    promoted_at TEXT,
    notes       TEXT,
    PRIMARY KEY (spec_id, version)
);

CREATE TABLE IF NOT EXISTS labeled_games (
    label_id        TEXT PRIMARY KEY,
    game_id         TEXT NOT NULL,
    spec_id         TEXT NOT NULL,
    spec_version    INTEGER NOT NULL CHECK (spec_version >= 1),
    label           INTEGER CHECK (label IS NULL OR label IN (0, 1)),
    evaluable       INTEGER NOT NULL DEFAULT 1 CHECK (evaluable IN (0, 1)),
    evidence_json   TEXT NOT NULL,
    labeler_version TEXT NOT NULL,
    labeled_at      TEXT NOT NULL,
    UNIQUE (game_id, spec_id, spec_version)
);

CREATE TABLE IF NOT EXISTS label_audits (
    audit_id          TEXT PRIMARY KEY,
    spec_id           TEXT NOT NULL,
    spec_version      INTEGER NOT NULL CHECK (spec_version >= 1),
    game_id           TEXT NOT NULL,
    sampled           INTEGER NOT NULL DEFAULT 1 CHECK (sampled IN (0, 1)),
    adjudication      TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    auditor           TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stat_results (
    stat_id          TEXT PRIMARY KEY,
    spec_id          TEXT NOT NULL,
    spec_version     INTEGER NOT NULL CHECK (spec_version >= 1),
    split            TEXT NOT NULL,
    n                INTEGER NOT NULL CHECK (n >= 0),
    positives        INTEGER NOT NULL CHECK (positives >= 0),
    risk_diff        REAL,
    ci_low           REAL,
    ci_high          REAL,
    odds_ratio       REAL,
    p_value          REAL CHECK (p_value IS NULL OR (p_value >= 0.0 AND p_value <= 1.0)),
    q_value          REAL CHECK (q_value IS NULL OR (q_value >= 0.0 AND q_value <= 1.0)),
    method           TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    computed_at      TEXT NOT NULL,
    CHECK (positives <= n)
);

CREATE TABLE IF NOT EXISTS validated_preconditions (
    spec_id         TEXT PRIMARY KEY,
    spec_version    INTEGER NOT NULL CHECK (spec_version >= 1),
    status          TEXT NOT NULL,
    acceptance_json TEXT NOT NULL,
    effect_json     TEXT NOT NULL,
    citations_json  TEXT NOT NULL,
    valid_from      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id   TEXT PRIMARY KEY,
    source_url    TEXT,
    domain        TEXT NOT NULL,
    title         TEXT,
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    snapshot_path TEXT,
    kind          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_links (
    evidence_id TEXT NOT NULL,
    ref_type    TEXT NOT NULL,
    ref_id      TEXT NOT NULL,
    supports    INTEGER NOT NULL DEFAULT 1 CHECK (supports IN (0, 1)),
    quote       TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (evidence_id, ref_type, ref_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id         TEXT PRIMARY KEY,
    slate_date     TEXT NOT NULL,
    games_json     TEXT NOT NULL,
    spec_set_hash  TEXT NOT NULL,
    config_hash    TEXT NOT NULL,
    status         TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    budget_seconds REAL,
    trace_path     TEXT
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key         TEXT PRIMARY KEY,
    game_id           TEXT NOT NULL,
    spec_set_hash     TEXT NOT NULL,
    evidence_hash     TEXT NOT NULL,
    scorer_version    TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    result_json       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    expires_at        TEXT
);

CREATE TABLE IF NOT EXISTS agent_events (
    event_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    agent       TEXT NOT NULL,
    phase       TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantine (
    record_id   TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    errors_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Explicit indexes for the access paths named in the plan. Primary keys already
-- index the identity columns, but these cover joins and scans used by the UI.
CREATE INDEX IF NOT EXISTS idx_teams_conference ON teams (conference_id);
CREATE INDEX IF NOT EXISTS idx_teams_venue ON teams (venue_id);
CREATE INDEX IF NOT EXISTS idx_games_season_week ON games (season, week);
CREATE INDEX IF NOT EXISTS idx_games_kickoff ON games (kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_game_fields_game_id ON game_fields (game_id);
CREATE INDEX IF NOT EXISTS idx_game_features_game_id ON game_features (game_id);
CREATE INDEX IF NOT EXISTS idx_spec_store_active ON spec_store (is_active, spec_id, version);
CREATE INDEX IF NOT EXISTS idx_labeled_games_game_id ON labeled_games (game_id);
CREATE INDEX IF NOT EXISTS idx_labeled_games_spec ON labeled_games (spec_id, spec_version);
CREATE INDEX IF NOT EXISTS idx_label_audits_game_id ON label_audits (game_id);
CREATE INDEX IF NOT EXISTS idx_stat_results_spec ON stat_results (spec_id, spec_version, split);
CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence (content_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_links_ref ON evidence_links (ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_key ON analysis_cache (cache_key);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_game_id ON analysis_cache (game_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_run_id ON agent_events (run_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_ts ON agent_events (ts);
