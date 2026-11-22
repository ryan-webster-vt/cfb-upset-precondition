"""SQLite database lifecycle, migration runner, and health verification.

The rest of the application never opens a SQLite connection directly: callers
ask ``Database`` for a session and use the typed repositories. This keeps raw
SQL confined to ``cfb_upset/store/`` and makes the migration gate a single
command (``python -m cfb_upset.store.db --init``).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cfb_upset.config import get_settings
from cfb_upset.errors import ConfigError
from cfb_upset.ids import Clock, SystemClock

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def utc_iso(value: datetime) -> str:
    """Serialise an aware datetime as a stable UTC ISO-8601 string."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, accepting both ``Z`` and ``+00:00``."""

    if value is None or value == "":
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class VerifyReport:
    """Result of ``Database.verify`` used by the CLI and tests."""

    path: str
    applied_migrations: list[str]
    table_counts: dict[str, int]
    missing_tables: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_tables and not self.errors


class Database:
    """A small connection factory around one SQLite file.

    A fresh connection is opened per session so repository calls are safe to
    use from worker threads and from short-lived CLI commands. ``:memory:`` is
    the one exception: it keeps a single shared connection because each new
    SQLite in-memory connection would otherwise see an empty database.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        migrations_dir: str | Path | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path is not None else None
        self.migrations_dir = (
            Path(migrations_dir).expanduser() if migrations_dir is not None else MIGRATIONS_DIR
        )
        self.clock = clock or SystemClock()
        self._shared: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ paths
    def resolved_path(self) -> Path:
        if self.path is None:
            self.path = Path(get_settings().sqlite_path).expanduser()
        return self.path

    @property
    def is_memory(self) -> bool:
        return str(self.path) == ":memory:"

    # -------------------------------------------------------------- connections
    def _new_connection(self) -> sqlite3.Connection:
        path = self.resolved_path()
        if not self.is_memory:
            path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if not self.is_memory:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection and commit on success / roll back on error."""

        if self.is_memory:
            if self._shared is None:
                self._shared = self._new_connection()
            connection = self._shared
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return

        connection = self._new_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None

    # -------------------------------------------------------------- migrations
    def _migration_files(self) -> list[tuple[str, Path]]:
        if not self.migrations_dir.exists():
            raise ConfigError(f"migrations directory does not exist: {self.migrations_dir}")
        files: list[tuple[str, Path]] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            version = path.stem.split("_", 1)[0]
            if not version:
                raise ConfigError(f"migration filename has no version prefix: {path.name}")
            files.append((version, path))
        if not files:
            raise ConfigError(f"no migrations found in {self.migrations_dir}")
        return files

    def _ensure_migration_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

    def applied_migrations(self) -> list[str]:
        with self.session() as connection:
            self._ensure_migration_table(connection)
            rows = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        return [row["version"] for row in rows]

    def initialize(self) -> list[str]:
        """Apply every pending migration and return the versions applied now."""

        applied_now: list[str] = []
        with self.session() as connection:
            self._ensure_migration_table(connection)
            done = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for version, path in self._migration_files():
                if version in done:
                    continue
                statements = _split_statements(path.read_text(encoding="utf-8"))
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, utc_iso(self.clock.now())),
                )
                applied_now.append(version)
        return applied_now

    # --------------------------------------------------------------- inspection
    def table_names(self) -> list[str]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.session() as connection:
            tables = [
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
            ]
            for table in tables:
                # Table names come from sqlite_master, never user input.
                counts[table] = int(
                    connection.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
                )
        return counts

    def verify(self) -> VerifyReport:
        expected = {
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
        errors: list[str] = []
        try:
            tables = set(self.table_names())
            missing = sorted(expected - tables)
            counts = self.table_counts()
            applied = self.applied_migrations()
            if not applied:
                errors.append("no migrations have been applied")
        except sqlite3.Error as exc:  # pragma: no cover - corrupt/locked DB path
            return VerifyReport(
                path=str(self.resolved_path()),
                applied_migrations=[],
                table_counts={},
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        return VerifyReport(
            path=str(self.resolved_path()),
            applied_migrations=applied,
            table_counts=counts,
            missing_tables=missing,
            errors=errors,
        )


def _split_statements(sql: str) -> list[str]:
    """Split a migration on semicolons, ignoring line comments and blanks.

    The checked-in migrations contain no semicolons inside string literals or
    triggers; if a later migration needs one, it should use ``executescript``
    semantics explicitly rather than silently changing this helper.
    """

    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement.rstrip(";").strip())
            buffer = []
    if buffer:
        statements.append("\n".join(buffer).strip())
    return [statement for statement in statements if statement]


def _print_report(report: VerifyReport) -> None:
    print(f"database: {report.path}")
    print(f"migrations: {', '.join(report.applied_migrations) or '(none)'}")
    if report.missing_tables:
        print(f"missing tables: {', '.join(report.missing_tables)}")
    for error in report.errors:
        print(f"error: {error}")
    print("table counts:")
    for table, count in report.table_counts.items():
        print(f"  {table:24s} {count:>8d}")
    print("status:", "OK" if report.ok else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CFB upset database utilities")
    parser.add_argument("--db", help="SQLite path (defaults to SQLITE_PATH / data/cfb.db)")
    parser.add_argument("--init", action="store_true", help="apply pending migrations")
    parser.add_argument("--verify", action="store_true", help="print table and row counts")
    parser.add_argument(
        "--migrations",
        help="override the migrations directory (testing / packaging)",
    )
    args = parser.parse_args(argv)

    if not args.init and not args.verify:
        parser.print_help()
        return 2

    try:
        database = Database(args.db, migrations_dir=args.migrations)
        if args.init:
            applied = database.initialize()
            print(f"applied migrations: {', '.join(applied) or '(none pending)'}")
        if args.verify:
            report = database.verify()
            _print_report(report)
            return 0 if report.ok else 1
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
