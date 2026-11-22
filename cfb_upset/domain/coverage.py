"""Coverage report for the historical corpus (R32).

The report answers four questions the P2 gate asks:

* how many games were stored per season/week, and are they all FBS-vs-FBS?
* what fraction of every column is populated, per season and per team?
* where did the favourite come from, and which fields are label-only?
* is any policy-admissible field stamped at or after kickoff? (must be zero)

All SQL lives in ``store.repositories.CoverageRepository``; this module is pure
aggregation plus rendering, so it is testable without a database.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cfb_upset.domain.leakage import LeakageError, policy_for
from cfb_upset.store.repositories import CoverageFieldRow, CoverageGameRow

# Fields the P2 pipeline deliberately does not collect. Weather lands in P7;
# listing it here keeps "unsupported" explicit rather than silently absent.
NOT_COLLECTED = ("weather",)

# Fields shown in the markdown per-team table; the JSON carries every field.
TEAM_TABLE_FIELDS = (
    "venue",
    "odds",
    "status",
    "conference_game",
    "neutral_site",
    "home_score",
    "away_score",
    "team_stats",
)


@dataclass(frozen=True)
class ColumnCoverage:
    field: str
    group: str | None
    admissible: bool
    rows: int
    non_null: int

    @property
    def pct(self) -> float:
        return round(100.0 * self.non_null / self.rows, 1) if self.rows else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "admissible": self.admissible,
            "rows": self.rows,
            "non_null": self.non_null,
            "pct": self.pct,
        }


@dataclass(frozen=True)
class TeamCoverage:
    team_id: str
    games: int
    fields: dict[str, ColumnCoverage]

    def as_dict(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "fields": {name: coverage.as_dict() for name, coverage in self.fields.items()},
        }


@dataclass
class CoverageReport:
    generated_at: datetime
    seasons: list[int]
    season_types: list[int]
    total_games: int
    games_by_season: dict[int, int]
    games_by_season_week: dict[str, int]
    overall: dict[str, ColumnCoverage]
    by_season: dict[int, dict[str, ColumnCoverage]]
    by_team: dict[str, TeamCoverage]
    favorite_sources: dict[str, int]
    market_prob_sources: dict[str, int]
    unsupported_fields: list[str]
    label_only_fields: list[str]
    leaked_admissible_fields: int
    leaked_examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.leaked_admissible_fields == 0 and self.total_games > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "seasons": self.seasons,
            "season_types": self.season_types,
            "total_games": self.total_games,
            "games_by_season": {str(k): v for k, v in sorted(self.games_by_season.items())},
            "games_by_season_week": dict(sorted(self.games_by_season_week.items())),
            "field_coverage": {
                name: coverage.as_dict() for name, coverage in sorted(self.overall.items())
            },
            "field_coverage_by_season": {
                str(season): {
                    name: coverage.as_dict() for name, coverage in sorted(columns.items())
                }
                for season, columns in sorted(self.by_season.items())
            },
            "team_coverage": {
                team_id: coverage.as_dict() for team_id, coverage in sorted(self.by_team.items())
            },
            "favorite_sources": self.favorite_sources,
            "market_prob_sources": self.market_prob_sources,
            "unsupported_fields": self.unsupported_fields,
            "label_only_fields": self.label_only_fields,
            "leaked_admissible_fields": self.leaked_admissible_fields,
            "leaked_examples": self.leaked_examples,
            "ok": self.ok,
        }

    def render_markdown(self) -> str:
        lines: list[str] = []
        stamp = self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"# Historical corpus coverage — {stamp}")
        lines.append("")
        lines.append(
            f"Seasons: **{', '.join(str(s) for s in self.seasons)}** · "
            f"season types: **{', '.join(str(t) for t in self.season_types)}** · "
            f"games: **{self.total_games}** · leakage: "
            f"**{'PASS' if self.leaked_admissible_fields == 0 else 'FAIL'}**"
        )
        lines.append("")
        lines.append("## Games per season")
        lines.append("")
        lines.append("| Season | Games | Weeks |")
        lines.append("| --- | ---: | ---: |")
        for season, count in sorted(self.games_by_season.items()):
            weeks = sum(1 for key in self.games_by_season_week if key.startswith(f"{season}:"))
            lines.append(f"| {season} | {count} | {weeks} |")
        lines.append("")
        lines.append("## Games per season/week")
        lines.append("")
        lines.append("| Season | Week | Games |")
        lines.append("| --- | ---: | ---: |")
        for (season, week), count in sorted(
            self._week_keys(),
            key=lambda item: (
                item[0][0],
                -1 if item[0][1] is None else item[0][1],
            ),
        ):
            lines.append(f"| {season} | {week} | {count} |")
        lines.append("")
        lines.append("## Field coverage (overall)")
        lines.append("")
        lines.append("| Field | Group | Non-null % | Rows | Admissible |")
        lines.append("| --- | --- | ---: | ---: | --- |")
        for name, coverage in sorted(self.overall.items()):
            lines.append(
                f"| `{name}` | {coverage.group or '-'} | {coverage.pct:.1f}% | "
                f"{coverage.rows} | {'yes' if coverage.admissible else 'label only'} |"
            )
        lines.append("")
        lines.append("## Field coverage by season")
        lines.append("")
        header = "| Field | " + " | ".join(str(s) for s in sorted(self.by_season)) + " |"
        divider = "| --- | " + " | ".join("---:" for _ in self.by_season) + " |"
        lines.append(header)
        lines.append(divider)
        for name in sorted(self.overall):
            cells = []
            for season in sorted(self.by_season):
                coverage = self.by_season[season].get(name)
                cells.append(f"{coverage.pct:.1f}%" if coverage else "-")
            lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("## Team coverage")
        lines.append("")
        lines.append("| Team | Games | " + " | ".join(TEAM_TABLE_FIELDS) + " |")
        lines.append("| --- | ---: | " + " | ".join("---:" for _ in TEAM_TABLE_FIELDS) + " |")
        for team_id, coverage in sorted(self.by_team.items(), key=lambda item: -item[1].games):
            cells = []
            for name in TEAM_TABLE_FIELDS:
                column = coverage.fields.get(name)
                cells.append(f"{column.pct:.0f}%" if column else "-")
            lines.append(f"| {team_id} | {coverage.games} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("## Favourite source distribution")
        lines.append("")
        for name, count in sorted(self.favorite_sources.items()):
            lines.append(f"- `{name}`: {count}")
        lines.append("")
        lines.append("## Market probability source distribution")
        lines.append("")
        for name, count in sorted(self.market_prob_sources.items()):
            lines.append(f"- `{name}`: {count}")
        lines.append("")
        lines.append("## Leakage check")
        lines.append("")
        lines.append(
            f"Policy-admissible fields with `known_at >= kickoff`: "
            f"**{self.leaked_admissible_fields}**"
        )
        if self.leaked_examples:
            for example in self.leaked_examples:
                lines.append(f"- {example}")
        lines.append("")
        lines.append("## Label-only fields (stored, never admitted)")
        lines.append("")
        lines.append(", ".join(f"`{name}`" for name in self.label_only_fields) or "-")
        lines.append("")
        lines.append("## Unsupported fields")
        lines.append("")
        lines.append(", ".join(f"`{name}`" for name in self.unsupported_fields) or "-")
        lines.append("")
        return "\n".join(lines)

    def _week_keys(self) -> list[tuple[tuple[int, int | None], int]]:
        parsed: list[tuple[tuple[int, int | None], int]] = []
        for key, count in self.games_by_season_week.items():
            season, week = key.split(":", 1)
            parsed.append(((int(season), None if week == "None" else int(week)), count))
        return parsed


def build_coverage(
    games: list[CoverageGameRow],
    fields: list[CoverageFieldRow],
    *,
    seasons: list[int],
    season_types: list[int],
    generated_at: datetime,
) -> CoverageReport:
    """Aggregate stored rows into a coverage report."""

    game_index = {game.game_id: game for game in games}
    games_by_season: Counter[int] = Counter(game.season for game in games)
    games_by_week: Counter[str] = Counter(f"{game.season}:{game.week}" for game in games)

    policies: dict[str, tuple[str | None, bool] | None] = {}
    unknown: set[str] = set()

    def policy(field_name: str) -> tuple[str | None, bool] | None:
        if field_name not in policies:
            try:
                resolved = policy_for(field_name)
                policies[field_name] = (resolved.group, resolved.admissible)
            except LeakageError:
                policies[field_name] = None
                unknown.add(field_name)
        return policies[field_name]

    rows_by_field: Counter[str] = Counter()
    non_null_by_field: Counter[str] = Counter()
    season_rows: dict[int, Counter[str]] = defaultdict(Counter)
    season_non_null: dict[int, Counter[str]] = defaultdict(Counter)
    team_rows: dict[str, Counter[str]] = defaultdict(Counter)
    team_non_null: dict[str, Counter[str]] = defaultdict(Counter)
    team_games: Counter[str] = Counter()

    for game in games:
        team_games[game.home_team_id] += 1
        team_games[game.away_team_id] += 1

    leaked = 0
    leaked_examples: list[str] = []
    favorite_sources: Counter[str] = Counter()
    market_prob_sources: Counter[str] = Counter()
    games_with_odds: set[str] = set()

    for row in fields:
        game = game_index.get(row.game_id)
        if game is None:
            continue
        resolved = policy(row.field_name)
        if resolved is None:
            continue
        present = _is_present(row.value)
        rows_by_field[row.field_name] += 1
        season_rows[game.season][row.field_name] += 1
        for team_id in (game.home_team_id, game.away_team_id):
            team_rows[team_id][row.field_name] += 1
        if not present:
            continue
        non_null_by_field[row.field_name] += 1
        season_non_null[game.season][row.field_name] += 1
        for team_id in (game.home_team_id, game.away_team_id):
            team_non_null[team_id][row.field_name] += 1
        admissible = resolved[1]
        if admissible and row.known_at_utc >= game.kickoff_utc:
            leaked += 1
            if len(leaked_examples) < 10:
                leaked_examples.append(
                    f"`{row.game_id}` `{row.field_name}` "
                    f"known_at={row.known_at_utc.isoformat()}"
                )
        if row.field_name == "odds" and isinstance(row.value, dict):
            games_with_odds.add(row.game_id)
            favorite_sources[str(row.value.get("favorite_source") or "unknown")] += 1
            market_prob_sources[str(row.value.get("market_prob_source") or "unknown")] += 1

    missing_odds = len(games) - len(games_with_odds)
    if missing_odds > 0:
        favorite_sources["unavailable"] += missing_odds
        market_prob_sources["unavailable"] += missing_odds

    overall: dict[str, ColumnCoverage] = {}
    for field_name in rows_by_field:
        resolved = policies.get(field_name) or (None, True)
        overall[field_name] = ColumnCoverage(
            field=field_name,
            group=resolved[0],
            admissible=resolved[1],
            rows=len(games),
            non_null=non_null_by_field[field_name],
        )

    by_season: dict[int, dict[str, ColumnCoverage]] = {}
    for season in sorted(games_by_season):
        columns: dict[str, ColumnCoverage] = {}
        for field_name in season_rows[season]:
            resolved = policies.get(field_name) or (None, True)
            columns[field_name] = ColumnCoverage(
                field=field_name,
                group=resolved[0],
                admissible=resolved[1],
                rows=games_by_season[season],
                non_null=season_non_null[season][field_name],
            )
        by_season[season] = columns

    by_team: dict[str, TeamCoverage] = {}
    for team_id, count in team_games.items():
        columns = {}
        for field_name in team_rows[team_id]:
            resolved = policies.get(field_name) or (None, True)
            columns[field_name] = ColumnCoverage(
                field=field_name,
                group=resolved[0],
                admissible=resolved[1],
                rows=count,
                non_null=team_non_null[team_id][field_name],
            )
        by_team[team_id] = TeamCoverage(team_id=team_id, games=count, fields=columns)

    label_only = sorted(name for name, coverage in overall.items() if not coverage.admissible)
    unsupported = sorted(unknown.union(NOT_COLLECTED))
    return CoverageReport(
        generated_at=generated_at,
        seasons=seasons,
        season_types=season_types,
        total_games=len(games),
        games_by_season=dict(games_by_season),
        games_by_season_week=dict(games_by_week),
        overall=overall,
        by_season=by_season,
        by_team=by_team,
        favorite_sources=dict(favorite_sources),
        market_prob_sources=dict(market_prob_sources),
        unsupported_fields=unsupported,
        label_only_fields=label_only,
        leaked_admissible_fields=leaked,
        leaked_examples=leaked_examples,
    )


def write_coverage(report: CoverageReport, directory: str | Path = "reports") -> tuple[Path, Path]:
    """Write ``coverage_<ts>.md`` and ``coverage_<ts>.json`` and return both paths."""

    target = Path(directory).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = target / f"coverage_{stamp}.md"
    json_path = target / f"coverage_{stamp}.json"
    markdown_path.write_text(report.render_markdown(), encoding="utf-8")
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return markdown_path, json_path


def _is_present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, dict | list) and not value:
        return False
    return True


__all__ = [
    "ColumnCoverage",
    "CoverageReport",
    "NOT_COLLECTED",
    "TEAM_TABLE_FIELDS",
    "TeamCoverage",
    "build_coverage",
    "write_coverage",
]
