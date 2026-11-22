"""Mandated chronological splits and their hard assertions (P3.4).

The split is a property of the season, not of the row order:

* ``dev``  = 2021, 2022, 2023
* ``val``  = 2024
* ``test`` = 2025

``assert_disjoint_order`` is deliberately strict. A modelling run must fail
loudly if a season is assigned twice, if a split is missing, or if the
chronology is violated. ``assert_pre_cutoff`` catches a row whose kickoff is at
or after the split's first game, which would indicate a shuffle or a leak.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

DEV_SEASONS = (2021, 2022, 2023)
VAL_SEASONS = (2024,)
TEST_SEASONS = (2025,)


class Split(str, Enum):
    DEV = "dev"
    VAL = "val"
    TEST = "test"


DEFAULT_SPLITS: dict[Split, tuple[int, ...]] = {
    Split.DEV: DEV_SEASONS,
    Split.VAL: VAL_SEASONS,
    Split.TEST: TEST_SEASONS,
}


@dataclass(frozen=True)
class SplitAssignment:
    split: Split
    first_season: int
    last_season: int
    seasons: tuple[int, ...]

    def contains(self, season: int) -> bool:
        return season in self.seasons


def split_for_season(season: int, splits: Mapping[Split, Sequence[int]] | None = None) -> Split:
    """Return the mandated split for ``season`` or raise ``ValueError``."""

    resolved = splits or DEFAULT_SPLITS
    matches = [split for split, seasons in resolved.items() if season in seasons]
    if not matches:
        raise ValueError(f"season {season} is outside the mandated 2021-2025 splits")
    if len(matches) > 1:
        raise ValueError(f"season {season} belongs to multiple splits: {matches}")
    return matches[0]


def assignments(
    splits: Mapping[Split, Sequence[int]] | None = None,
) -> dict[Split, SplitAssignment]:
    resolved = splits or DEFAULT_SPLITS
    result: dict[Split, SplitAssignment] = {}
    for split, seasons in resolved.items():
        ordered = tuple(sorted(int(season) for season in seasons))
        if not ordered:
            raise ValueError(f"split {split.value} is empty")
        result[split] = SplitAssignment(split, ordered[0], ordered[-1], ordered)
    return result


def assert_disjoint_order(splits: Mapping[Split, Sequence[int]] | None = None) -> None:
    """Raise unless splits are non-empty, disjoint, and strictly chronological."""

    resolved = splits or DEFAULT_SPLITS
    if set(resolved) != set(Split):
        missing = set(Split) - set(resolved)
        raise AssertionError(f"missing splits: {sorted(split.value for split in missing)}")
    seen: dict[int, Split] = {}
    for split, seasons in resolved.items():
        if not seasons:
            raise AssertionError(f"split {split.value} is empty")
        for season in seasons:
            if season in seen:
                raise AssertionError(
                    f"season {season} appears in both {seen[season].value} and {split.value}"
                )
            seen[season] = split
    order = assignments(resolved)
    if not (
        order[Split.DEV].last_season < order[Split.VAL].first_season
        and order[Split.VAL].last_season < order[Split.TEST].first_season
    ):
        raise AssertionError("splits are not chronologically ordered: dev < val < test")


def assert_pre_cutoff(
    rows: Iterable[tuple[int, datetime]],
    split: Split,
    *,
    splits: Mapping[Split, Sequence[int]] | None = None,
) -> None:
    """Raise if a row's season is not assigned to ``split``.

    The kickoff is only checked for timezone awareness; the season is the split
    key, so a row cannot drift into another split by being out of order.
    """

    allowed = set((splits or DEFAULT_SPLITS)[split])
    for season, kickoff in rows:
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise AssertionError("split assertion received a naive kickoff")
        if season not in allowed:
            raise AssertionError(f"row season {season} is not in split {split.value}")
        if split_for_season(season, splits) is not split:
            raise AssertionError(f"row season {season} maps to a different split")


def assert_split_boundaries(rows: Iterable[tuple[Split, datetime]]) -> None:
    """Raise unless every dev kickoff precedes val, and val precedes test."""

    bounds: dict[Split, list[datetime]] = {split: [] for split in Split}
    for split, kickoff in rows:
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise AssertionError("split boundary assertion received a naive kickoff")
        bounds[split].append(kickoff)
    if any(not values for values in bounds.values()):
        raise AssertionError("cannot assert boundaries: a split has no rows")
    if max(bounds[Split.DEV]) >= min(bounds[Split.VAL]):
        raise AssertionError("dev rows are not strictly before val rows")
    if max(bounds[Split.VAL]) >= min(bounds[Split.TEST]):
        raise AssertionError("val rows are not strictly before test rows")


def split_counts(seasons: Iterable[int]) -> dict[str, int]:
    counts = {split.value: 0 for split in Split}
    for season in seasons:
        counts[split_for_season(season).value] += 1
    return counts


__all__ = [
    "DEFAULT_SPLITS",
    "DEV_SEASONS",
    "TEST_SEASONS",
    "VAL_SEASONS",
    "Split",
    "SplitAssignment",
    "assert_disjoint_order",
    "assert_pre_cutoff",
    "assert_split_boundaries",
    "assignments",
    "split_counts",
    "split_for_season",
]
