"""Post-kickoff admission policy, expressed as data.

Every value that can influence a label, a feature, a score, or a rationale
must pass ``admit`` before use. The strict comparison is deliberate: a closing
line stamped exactly at kickoff is excluded by ``known_at < kickoff``.

The policy table is the single source of truth. Adapters may *collect* a field
with any timestamp, but downstream consumers call ``admit`` and a violation is
both logged and raised as ``LeakageError``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cfb_upset.errors import LeakageError

logger = logging.getLogger("cfb_upset.leakage")


@dataclass(frozen=True)
class FieldPolicy:
    """One admission rule.

    ``offset`` is subtracted from kickoff to derive a default ``known_at``.
    ``admissible=False`` marks a field that is *never* a feature (labels only),
    even if its timestamp is technically earlier.
    """

    group: str
    offset: timedelta | None = None
    admissible: bool = True
    note: str = ""


_SCHEDULE = timedelta(days=7)
_OPENING_ODDS = timedelta(hours=72)
_WEATHER = timedelta(hours=24)

# Exact names are checked first, then ordered prefixes. Keep the table small
# and explicit: an unrecognised field is rejected rather than assumed safe.
EXACT_POLICIES: dict[str, FieldPolicy] = {
    # schedule / identity
    "game_id": FieldPolicy("schedule", _SCHEDULE),
    "season": FieldPolicy("schedule", _SCHEDULE),
    "week": FieldPolicy("schedule", _SCHEDULE),
    "season_type": FieldPolicy("schedule", _SCHEDULE),
    "slate_date": FieldPolicy("schedule", _SCHEDULE),
    "kickoff_utc": FieldPolicy("schedule", _SCHEDULE),
    "status": FieldPolicy("schedule", _SCHEDULE),
    "neutral_site": FieldPolicy("schedule", _SCHEDULE),
    "conference_game": FieldPolicy("schedule", _SCHEDULE),
    "broadcast": FieldPolicy("schedule", _SCHEDULE),
    "home": FieldPolicy("team_identity", _SCHEDULE),
    "away": FieldPolicy("team_identity", _SCHEDULE),
    "home_team_id": FieldPolicy("team_identity", _SCHEDULE),
    "away_team_id": FieldPolicy("team_identity", _SCHEDULE),
    "team_id": FieldPolicy("team_identity", _SCHEDULE),
    "school": FieldPolicy("team_identity", _SCHEDULE),
    "nickname": FieldPolicy("team_identity", _SCHEDULE),
    "abbreviation": FieldPolicy("team_identity", _SCHEDULE),
    "conference": FieldPolicy("team_identity", _SCHEDULE),
    "conference_id": FieldPolicy("team_identity", _SCHEDULE),
    "is_fbs": FieldPolicy("team_identity", _SCHEDULE),
    "color": FieldPolicy("team_identity", _SCHEDULE),
    "alt_color": FieldPolicy("team_identity", _SCHEDULE),
    "logo_url": FieldPolicy("team_identity", _SCHEDULE),
    "venue": FieldPolicy("venue", _SCHEDULE),
    "venue_id": FieldPolicy("venue", _SCHEDULE),
    "city": FieldPolicy("venue", _SCHEDULE),
    "state": FieldPolicy("venue", _SCHEDULE),
    "country": FieldPolicy("venue", _SCHEDULE),
    "indoor": FieldPolicy("venue", _SCHEDULE),
    "grass": FieldPolicy("venue", _SCHEDULE),
    "lat": FieldPolicy("venue", _SCHEDULE),
    "lon": FieldPolicy("venue", _SCHEDULE),
    "altitude_m": FieldPolicy("venue", _SCHEDULE),
    "tz": FieldPolicy("venue", _SCHEDULE),
    # rankings: caller passes the earliest kickoff of the game week - 1h
    "rank": FieldPolicy("rankings", timedelta(hours=1)),
    "poll_rank": FieldPolicy("rankings", timedelta(hours=1)),
    "previous_rank": FieldPolicy("rankings", timedelta(hours=1)),
    "rank_delta": FieldPolicy("rankings", timedelta(hours=1)),
    # odds: only the open number is admissible
    "spread_open": FieldPolicy("opening_odds", _OPENING_ODDS),
    "over_under_open": FieldPolicy("opening_odds", _OPENING_ODDS),
    "opening_spread": FieldPolicy("opening_odds", _OPENING_ODDS),
    "opening_total": FieldPolicy("opening_odds", _OPENING_ODDS),
    "odds": FieldPolicy("opening_odds", _OPENING_ODDS),
    "market_prob": FieldPolicy("opening_odds", _OPENING_ODDS),
    "favorite_source": FieldPolicy("opening_odds", _OPENING_ODDS),
    "line_provider": FieldPolicy("opening_odds", _OPENING_ODDS),
    "market_prob_source": FieldPolicy("opening_odds", _OPENING_ODDS),
    "spread": FieldPolicy("closing_odds", None, admissible=False, note="closing line at kickoff"),
    "over_under": FieldPolicy(
        "closing_odds", None, admissible=False, note="closing total at kickoff"
    ),
    "closing_spread": FieldPolicy("closing_odds", None, admissible=False),
    "closing_total": FieldPolicy("closing_odds", None, admissible=False),
    # weather
    "weather": FieldPolicy("weather", _WEATHER),
    "temperature_c": FieldPolicy("weather", _WEATHER),
    "wind_kph": FieldPolicy("weather", _WEATHER),
    "precipitation_mm": FieldPolicy("weather", _WEATHER),
    "condition": FieldPolicy("weather", _WEATHER),
    "lead_hours": FieldPolicy("weather", _WEATHER),
    # post-game, labels only
    "home_score": FieldPolicy("box_score", None, admissible=False),
    "away_score": FieldPolicy("box_score", None, admissible=False),
    "winner_team_id": FieldPolicy("box_score", None, admissible=False),
    "team_stats": FieldPolicy("box_score", None, admissible=False),
    "final_score": FieldPolicy("box_score", None, admissible=False),
    "margin": FieldPolicy("box_score", None, admissible=False),
    "upset": FieldPolicy("box_score", None, admissible=False),
    # articles / notes: caller must supply published_at-derived known_at
    "citation": FieldPolicy("article", None),
    "quote": FieldPolicy("article", None),
    "published_at": FieldPolicy("article", None),
    "article": FieldPolicy("article", None),
    "injury_note": FieldPolicy("article", None),
    "depth_chart": FieldPolicy("article", None),
}

PREFIX_POLICIES: list[tuple[str, FieldPolicy]] = [
    # rolling pre-game state: admissible only with an explicit pre-kickoff stamp
    ("rest_days", FieldPolicy("rolling_stats")),
    ("travel_km", FieldPolicy("rolling_stats")),
    ("wins", FieldPolicy("rolling_stats")),
    ("losses", FieldPolicy("rolling_stats")),
    ("win_pct", FieldPolicy("rolling_stats")),
    ("point_diff", FieldPolicy("rolling_stats")),
    ("scoring_", FieldPolicy("rolling_stats")),
    ("defensive_", FieldPolicy("rolling_stats")),
    ("sos", FieldPolicy("rolling_stats")),
    ("last3_", FieldPolicy("rolling_stats")),
    ("pace_", FieldPolicy("rolling_stats")),
    ("look_ahead", FieldPolicy("rolling_stats")),
    ("short_week", FieldPolicy("rolling_stats")),
    ("post_bye", FieldPolicy("rolling_stats")),
    ("elo", FieldPolicy("rolling_stats")),
    ("strength_", FieldPolicy("rolling_stats")),
    ("market_", FieldPolicy("rolling_stats")),
    ("spec_", FieldPolicy("derived")),
    ("feature_", FieldPolicy("derived")),
    ("matched_", FieldPolicy("derived")),
    ("boxscore", FieldPolicy("box_score", None, admissible=False)),
    ("postgame", FieldPolicy("box_score", None, admissible=False)),
    ("closing_", FieldPolicy("closing_odds", None, admissible=False)),
    ("weather_", FieldPolicy("weather", _WEATHER)),
    ("rank_", FieldPolicy("rankings", timedelta(hours=1))),
]


def policy_for(field: str) -> FieldPolicy:
    """Return the admission policy for ``field`` or reject an unknown name."""

    name = field.strip()
    if name in EXACT_POLICIES:
        return EXACT_POLICIES[name]
    lowered = name.lower()
    for prefix, policy in PREFIX_POLICIES:
        if lowered.startswith(prefix):
            return policy
    raise LeakageError(
        f"field {field!r} is not in the leakage policy; add it to "
        "cfb_upset.domain.leakage before using it"
    )


def derive_known_at(
    field: str,
    kickoff: datetime,
    *,
    week_earliest_kickoff: datetime | None = None,
    provider_time: datetime | None = None,
) -> datetime:
    """Derive the conservative ``known_at`` for a field group.

    Rankings use the earliest kickoff of the week minus one hour; opening odds
    use ``kickoff - 72h`` unless the provider reported an open timestamp. A
    closing line maps to kickoff itself, which ``admit`` then excludes.
    """

    _require_aware(kickoff, "kickoff")
    policy = policy_for(field)
    if provider_time is not None:
        return _require_aware(provider_time, "provider_time")
    if policy.group == "rankings":
        base = week_earliest_kickoff or kickoff
        return _require_aware(base, "week_earliest_kickoff") - timedelta(hours=1)
    if policy.group == "closing_odds":
        return kickoff
    if policy.group == "article":
        raise LeakageError(
            f"field {field!r} needs a published_at timestamp; no default can be assumed"
        )
    if policy.offset is None:
        raise LeakageError(
            f"field {field!r} is rolling state and needs an explicit pre-kickoff known_at"
        )
    return kickoff - policy.offset


def admit(
    field: str,
    known_at: datetime,
    kickoff: datetime,
    *,
    source: str | None = None,
) -> bool:
    """Return True when a field is admissible, else log and raise ``LeakageError``.

    The comparison is strict (``known_at < kickoff``), so a closing line or a
    post-game box score is never admitted.
    """

    _require_aware(kickoff, "kickoff")
    _require_aware(known_at, "known_at")
    policy = policy_for(field)
    if not policy.admissible:
        _violation(field, known_at, kickoff, source, policy)
    if known_at >= kickoff:
        _violation(field, known_at, kickoff, source, policy)
    return True


def is_admitted(
    field: str,
    known_at: datetime | None,
    kickoff: datetime,
    *,
    source: str | None = None,
) -> bool:
    """Boolean form used by filters; unknown/None fields are not admitted."""

    if known_at is None:
        logger.warning("leakage: field=%s has no known_at; excluded source=%s", field, source)
        return False
    try:
        return admit(field, known_at, kickoff, source=source)
    except LeakageError:
        return False


def filter_fields(
    fields: dict[str, tuple[Any, datetime | None]],
    kickoff: datetime,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Drop fields that fail admission; keep values that are provably pre-game."""

    admitted: dict[str, Any] = {}
    for field, (value, known_at) in fields.items():
        if is_admitted(field, known_at, kickoff, source=source):
            admitted[field] = value
    return admitted


def assert_feature_row(
    features: dict[str, tuple[Any, datetime | None]],
    kickoff: datetime,
    *,
    source: str | None = None,
) -> None:
    """Raise on the first inadmissible feature; used by the P3 feature builder."""

    for field, (_value, known_at) in features.items():
        if known_at is None:
            raise LeakageError(f"feature {field!r} has no known_at")
        admit(field, known_at, kickoff, source=source)


def _violation(
    field: str,
    known_at: datetime,
    kickoff: datetime,
    source: str | None,
    policy: FieldPolicy,
) -> None:
    detail = policy.note or policy.group
    logger.warning(
        "leakage violation: field=%s known_at=%s kickoff=%s group=%s source=%s",
        field,
        known_at.isoformat(),
        kickoff.isoformat(),
        detail,
        source,
    )
    raise LeakageError(
        f"{field!r} is not admissible: known_at={known_at.isoformat()} "
        f"kickoff={kickoff.isoformat()} ({detail})"
    )


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "EXACT_POLICIES",
    "PREFIX_POLICIES",
    "FieldPolicy",
    "admit",
    "assert_feature_row",
    "derive_known_at",
    "filter_fields",
    "is_admitted",
    "policy_for",
]
