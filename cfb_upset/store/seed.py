"""Seed ``teams`` and ``venues`` from a checked-in CSV and optional CFBD data.

The CSV is the deterministic offline seed. Live CFBD ``/venues`` rows are
overlaid when a key is available; any field CFBD leaves null (elevation 55.6%
missing, timezone 57.4% missing, lat/lon 5.6% missing in the sampled 2025
response) is filled from the CSV rather than stored as null.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from cfb_upset.contracts import TeamInfo, VenueInfo
from cfb_upset.store.repositories import Repositories

DATA_DIR = Path(__file__).with_name("data")
TEAMS_CSV = DATA_DIR / "teams_fallback.csv"
VENUES_CSV = DATA_DIR / "venues_fallback.csv"


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _optional_float(value: str | None) -> float | None:
    text = _optional(value)
    return float(text) if text is not None else None


def _optional_bool(value: str | None) -> bool | None:
    text = _optional(value)
    if text is None:
        return None
    return text.lower() in {"1", "true", "yes", "y"}


def _required_bool(value: str | None, default: bool = False) -> bool:
    parsed = _optional_bool(value)
    return default if parsed is None else parsed


def load_team_rows(path: str | Path = TEAMS_CSV) -> list[TeamInfo]:
    rows: list[TeamInfo] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                TeamInfo(
                    team_id=raw["team_id"].strip(),
                    school=raw["school"].strip(),
                    nickname=_optional(raw["nickname"]),
                    conference=_optional(raw["conference_id"]),
                    is_fbs=_required_bool(raw["is_fbs"], True),
                    color=_optional(raw["color"]),
                    alt_color=_optional(raw["alt_color"]),
                    logo_url=_optional(raw["logo_url"]),
                )
            )
    return rows


def load_venue_rows(path: str | Path = VENUES_CSV) -> list[VenueInfo]:
    rows: list[VenueInfo] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                VenueInfo(
                    venue_id=raw["venue_id"].strip(),
                    name=raw["name"].strip(),
                    city=_optional(raw["city"]),
                    state=_optional(raw["state"]),
                    country=_optional(raw["country"]),
                    indoor=_optional_bool(raw["indoor"]),
                    grass=_optional_bool(raw["grass"]),
                    lat=_optional_float(raw["lat"]),
                    lon=_optional_float(raw["lon"]),
                    altitude_m=_optional_float(raw["altitude_m"]),
                    tz=_optional(raw["tz"]),
                    source=_optional(raw["source"]),
                )
            )
    return rows


def seed_teams(
    repositories: Repositories,
    *,
    path: str | Path = TEAMS_CSV,
) -> int:
    rows = load_team_rows(path)
    with Path(path).open(newline="", encoding="utf-8") as handle:
        venue_by_team = {
            raw["team_id"].strip(): _optional(raw["venue_id"]) for raw in csv.DictReader(handle)
        }
    for team in rows:
        repositories.teams.upsert(team, venue_id=venue_by_team.get(team.team_id))
    return len(rows)


def _merge_venue(fallback: VenueInfo | None, live: VenueInfo) -> VenueInfo:
    if fallback is None:
        return live
    data: dict[str, Any] = live.model_dump()
    for field_name, value in fallback.model_dump().items():
        if data.get(field_name) is None and value is not None:
            data[field_name] = value
    data["source"] = "cfbd+fallback" if data != live.model_dump() else live.source or "cfbd"
    return VenueInfo.model_validate(data)


def seed_venues(
    repositories: Repositories,
    *,
    path: str | Path = VENUES_CSV,
    cfbd_venues: list[VenueInfo] | None = None,
) -> int:
    fallback = {venue.venue_id: venue for venue in load_venue_rows(path) if venue.venue_id}
    merged: dict[str, VenueInfo] = dict(fallback)
    for venue in cfbd_venues or []:
        if not venue.venue_id:
            continue
        merged[venue.venue_id] = _merge_venue(fallback.get(venue.venue_id), venue)
    for venue in merged.values():
        repositories.venues.upsert(venue)
    return len(merged)


async def seed_from_cfbd(repositories: Repositories, adapter: Any) -> int:
    """Fetch ``/venues`` through an adapter and merge it over the CSV seed."""

    venues = await adapter.fetch_venues()
    return seed_venues(repositories, cfbd_venues=venues)


def seed_all(repositories: Repositories) -> dict[str, int]:
    """Seed the offline tables; safe to call repeatedly."""

    return {
        "teams": seed_teams(repositories),
        "venues": seed_venues(repositories),
    }


__all__ = [
    "TEAMS_CSV",
    "VENUES_CSV",
    "load_team_rows",
    "load_venue_rows",
    "seed_all",
    "seed_from_cfbd",
    "seed_teams",
    "seed_venues",
]
