"""SQLite migration runner, verification, and CLI acceptance."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cfb_upset.store.db import Database, main

EXPECTED_TABLES = {
    "teams",
    "venues",
    "games",
    "game_fields",
    "game_features",
    "precondition_spec",
    "spec_store",
    "labeled_games",
    "label_audits",
    "stat_results",
    "validated_preconditions",
    "evidence",
    "evidence_links",
    "analysis_runs",
    "analysis_cache",
    "agent_events",
    "quarantine",
    "schema_migrations",
}


def test_init_creates_every_table(tmp_path: Path) -> None:
    database = Database(tmp_path / "cfb.db")
    applied = database.initialize()
    assert applied == ["0001"]
    assert EXPECTED_TABLES <= set(database.table_names())


def test_init_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    assert database.initialize() == []
    assert database.applied_migrations() == ["0001"]


def test_verify_reports_counts_and_status(tmp_path: Path) -> None:
    database = Database(tmp_path / "cfb.db")
    database.initialize()
    report = database.verify()
    assert report.ok
    assert report.missing_tables == []
    assert report.table_counts["schema_migrations"] == 1
    assert set(EXPECTED_TABLES) <= set(report.table_counts)


def test_verify_fails_without_migrations(tmp_path: Path) -> None:
    database = Database(tmp_path / "empty.db")
    report = database.verify()
    assert not report.ok
    assert "no migrations have been applied" in report.errors
    assert EXPECTED_TABLES <= set(report.missing_tables)


def test_cli_init_and_verify(tmp_path: Path, capsys) -> None:
    path = tmp_path / "cli.db"
    assert main(["--db", str(path), "--init"]) == 0
    assert "applied migrations: 0001" in capsys.readouterr().out
    assert main(["--db", str(path), "--verify"]) == 0
    output = capsys.readouterr().out
    assert "status: OK" in output
    assert "teams" in output


def test_module_cli_runs_from_a_fresh_process(tmp_path: Path) -> None:
    path = tmp_path / "module.db"
    result = subprocess.run(
        [sys.executable, "-m", "cfb_upset.store.db", "--db", str(path), "--init"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    verify = subprocess.run(
        [sys.executable, "-m", "cfb_upset.store.db", "--db", str(path), "--verify"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert "status: OK" in verify.stdout
