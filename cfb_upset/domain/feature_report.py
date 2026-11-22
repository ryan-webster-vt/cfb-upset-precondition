"""P3 feature availability and leakage report.

The report is the gate evidence for P3: it shows the feature version, the
number of games and rows, per-feature coverage by season, market-source
coverage, split counts, label coverage, and the leakage audit result.

Aggregation is pure. ``pipelines/build_features.py`` supplies the computed
``FeatureResult`` and writes both the markdown and the JSON.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cfb_upset.domain.features import FeatureConfig, FeatureResult
from cfb_upset.domain.splits import Split, split_counts, split_for_season


@dataclass(frozen=True)
class FeatureCoverage:
    feature: str
    rows: int
    non_null: int

    @property
    def pct(self) -> float:
        return round(100.0 * self.non_null / self.rows, 1) if self.rows else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "non_null": self.non_null, "pct": self.pct}


@dataclass
class FeatureReport:
    generated_at: datetime
    config: FeatureConfig
    games: int
    rows: int
    seasons: list[int]
    coverage: dict[str, dict[int, FeatureCoverage]]
    market_sources: dict[str, int]
    market_prob_sources: dict[str, int]
    line_providers: dict[str, int]
    split_counts: dict[str, int]
    labels: int
    upsets: int
    label_unavailable: int
    leaked: int
    unknown_fields: list[str]
    violations: list[str] = field(default_factory=list)
    worst_teams: list[tuple[str, float, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.leaked == 0 and not self.unknown_fields

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "config": self.config.as_dict(),
            "games": self.games,
            "rows": self.rows,
            "seasons": self.seasons,
            "leakage": {
                "ok": self.ok,
                "leaked": self.leaked,
                "unknown_fields": self.unknown_fields,
                "violations": self.violations,
            },
            "splits": self.split_counts,
            "market": {
                "favorite_sources": self.market_sources,
                "market_prob_sources": self.market_prob_sources,
                "line_providers": self.line_providers,
            },
            "labels": {
                "rows": self.labels,
                "upsets": self.upsets,
                "unavailable": self.label_unavailable,
            },
            "coverage": {
                feature: {
                    str(season): coverage.as_dict()
                    for season, coverage in sorted(by_season.items())
                }
                for feature, by_season in sorted(self.coverage.items())
            },
            "worst_teams": [
                {"team_id": team_id, "missing_pct": round(100.0 * missing, 1), "games": games}
                for team_id, missing, games in self.worst_teams
            ],
        }

    def to_markdown(self) -> str:
        seasons = self.seasons
        header = "| feature | overall % | " + " | ".join(str(season) for season in seasons) + " |"
        divider = "| --- | ---: | " + " | ".join("---:" for _ in seasons) + " |"
        lines = [
            "# Feature availability — P3",
            "",
            f"- generated: `{self.generated_at.isoformat()}`",
            f"- feature version: `{self.config.feature_version}`",
            f"- games: **{self.games}**",
            f"- feature rows: **{self.rows}**",
            f"- seasons: {', '.join(str(season) for season in seasons)}",
            f"- leakage: **{'PASS' if self.ok else 'FAIL'}** "
            f"({self.leaked} leaked, {len(self.unknown_fields)} unknown fields)",
            "- splits: "
            + ", ".join(f"{name}={count}" for name, count in self.split_counts.items()),
            f"- labels: {self.labels} (upsets {self.upsets}, unavailable {self.label_unavailable})",
            "",
            "## Leakage audit",
            "",
        ]
        if self.ok:
            lines.append("Every `game_features` row has `known_at < kickoff`.")
        else:
            lines.append(f"Leaked rows: **{self.leaked}**.")
            lines.extend(f"- `{violation}`" for violation in self.violations[:20])
            if self.unknown_fields:
                lines.append(f"- unknown policy fields: {', '.join(self.unknown_fields)}")
        lines.extend(
            [
                "",
                "## Market coverage",
                "",
                "| favorite source | games |",
                "| --- | ---: |",
            ]
        )
        for name, count in sorted(
            self.market_sources.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| `{name}` | {count} |")
        lines.extend(
            [
                "",
                "| market probability source | games |",
                "| --- | ---: |",
            ]
        )
        for name, count in sorted(
            self.market_prob_sources.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| `{name}` | {count} |")
        lines.extend(
            [
                "",
                "| line provider | games |",
                "| --- | ---: |",
            ]
        )
        for name, count in sorted(
            self.line_providers.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"| `{name}` | {count} |")
        lines.extend(
            [
                "",
                "## Coverage by feature × season",
                "",
                header,
                divider,
            ]
        )
        for feature, by_season in sorted(self.coverage.items()):
            overall_rows = sum(item.rows for item in by_season.values())
            overall_non_null = sum(item.non_null for item in by_season.values())
            overall = round(100.0 * overall_non_null / overall_rows, 1) if overall_rows else 0.0
            cells = [
                f"{by_season[season].pct:.1f}" if season in by_season else "—" for season in seasons
            ]
            lines.append(f"| `{feature}` | {overall:.1f} | " + " | ".join(cells) + " |")
        if self.worst_teams:
            lines.extend(
                [
                    "",
                    "## Teams with the most missing feature values",
                    "",
                    "| team | missing % | games |",
                    "| --- | ---: | ---: |",
                ]
            )
            for team_id, missing, games in self.worst_teams:
                lines.append(f"| `{team_id}` | {100.0 * missing:.1f} | {games} |")
        lines.extend(
            [
                "",
                "## Reproducibility",
                "",
                "```json",
                json.dumps(self.config.as_dict(), indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
        return "\n".join(lines)


def build_feature_report(
    result: FeatureResult,
    *,
    generated_at: datetime | None = None,
) -> FeatureReport:
    stamp = generated_at or datetime.now(UTC)
    games = result.wide_rows
    seasons = sorted({int(row["season"]) for row in games})
    season_by_game = _season_by_game(games)
    coverage: dict[str, dict[int, FeatureCoverage]] = {}
    for row in result.rows:
        season = season_by_game.get(row.game_id)
        if season is None:
            continue
        by_season = coverage.setdefault(row.feature_name, {})
        current = by_season.get(season, FeatureCoverage(row.feature_name, 0, 0))
        by_season[season] = FeatureCoverage(
            row.feature_name,
            current.rows + 1,
            current.non_null + int(row.value is not None),
        )

    market_sources: Counter[str] = Counter()
    prob_sources: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    for derived in result.fields:
        if derived.field_name == "favorite_source":
            market_sources[str(derived.value)] += 1
        elif derived.field_name == "market_prob_source":
            prob_sources[str(derived.value)] += 1
        elif derived.field_name == "line_provider":
            providers[str(derived.value)] += 1

    label_unavailable = sum(1 for label in result.labels if label.upset is None)
    upsets = sum(1 for label in result.labels if label.upset is True)
    feature_names = sorted({row.feature_name for row in result.rows})
    worst = _worst_teams(games, feature_names)
    counts = split_counts(int(row["season"]) for row in games)
    return FeatureReport(
        generated_at=stamp,
        config=result.config,
        games=result.games,
        rows=len(result.rows),
        seasons=seasons,
        coverage=coverage,
        market_sources=dict(market_sources),
        market_prob_sources=dict(prob_sources),
        line_providers=dict(providers),
        split_counts=counts,
        labels=len(result.labels),
        upsets=upsets,
        label_unavailable=label_unavailable,
        leaked=result.audit.leaked,
        unknown_fields=result.audit.unknown_fields,
        violations=result.audit.violations,
        worst_teams=worst,
    )


def write_feature_report(
    report: FeatureReport,
    directory: str | Path = "reports",
    *,
    prefix: str = "features",
) -> tuple[Path, Path]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    markdown = target / f"{prefix}_{stamp}.md"
    payload = target / f"{prefix}_{stamp}.json"
    markdown.write_text(report.to_markdown(), encoding="utf-8")
    payload.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return markdown, payload


def _season_by_game(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {str(row["game_id"]): int(row["season"]) for row in rows}


def _worst_teams(
    rows: Sequence[dict[str, Any]], feature_names: Iterable[str], *, limit: int = 20
) -> list[tuple[str, float, int]]:
    names = list(feature_names)
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        for side in ("home_team_id", "away_team_id"):
            team_id = str(row[side])
            bucket = totals[team_id]
            bucket[1] += len(names)
            bucket[0] += sum(1 for name in names if row.get(name) is None)
    scored: list[tuple[str, float, int]] = []
    for team_id, (missing, total) in totals.items():
        if total == 0:
            continue
        games = total // len(names) if names else 0
        if games < 5:
            continue
        scored.append((team_id, missing / total, games))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]


def split_vector(rows: Sequence[dict[str, Any]]) -> list[Split]:
    return [split_for_season(int(row["season"])) for row in rows]


__all__ = [
    "FeatureCoverage",
    "FeatureReport",
    "build_feature_report",
    "split_vector",
    "write_feature_report",
]
