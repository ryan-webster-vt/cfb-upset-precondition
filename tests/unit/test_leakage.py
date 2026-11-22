"""Leakage policy: strict pre-kickoff admission and fail-closed derivation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cfb_upset.domain.leakage import (
    admit,
    assert_feature_row,
    derive_known_at,
    filter_fields,
    is_admitted,
    policy_for,
)
from cfb_upset.errors import LeakageError

KICKOFF = datetime(2026, 11, 28, 17, 0, tzinfo=UTC)


def test_admit_accepts_a_pre_kickoff_value() -> None:
    assert admit("spread_open", KICKOFF - timedelta(hours=1), KICKOFF)


def test_admit_rejects_known_at_equal_to_kickoff() -> None:
    with pytest.raises(LeakageError, match="not admissible"):
        admit("spread_open", KICKOFF, KICKOFF)


def test_admit_rejects_post_kickoff_information() -> None:
    with pytest.raises(LeakageError):
        admit("weather", KICKOFF + timedelta(seconds=1), KICKOFF)
    with pytest.raises(LeakageError):
        admit("home_score", KICKOFF - timedelta(days=30), KICKOFF)


def test_closing_lines_are_never_admitted_even_before_kickoff() -> None:
    with pytest.raises(LeakageError, match="closing line"):
        admit("spread", KICKOFF - timedelta(days=1), KICKOFF)
    with pytest.raises(LeakageError):
        admit("over_under", KICKOFF - timedelta(days=1), KICKOFF)
    with pytest.raises(LeakageError):
        admit("closing_spread", KICKOFF - timedelta(days=1), KICKOFF)


def test_unknown_fields_are_rejected_rather_than_assumed_safe() -> None:
    with pytest.raises(LeakageError, match="not in the leakage policy"):
        policy_for("mystery_field_at_kickoff")
    with pytest.raises(LeakageError, match="not in the leakage policy"):
        admit("mystery_field_at_kickoff", KICKOFF - timedelta(days=1), KICKOFF)


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(LeakageError, match="timezone-aware"):
        admit("spread_open", datetime(2026, 11, 28, 12, 0), KICKOFF)
    with pytest.raises(LeakageError, match="timezone-aware"):
        admit("spread_open", KICKOFF - timedelta(hours=1), datetime(2026, 11, 28, 17, 0))


def test_derive_known_at_for_schedule_and_odds() -> None:
    assert derive_known_at("kickoff_utc", KICKOFF) == KICKOFF - timedelta(days=7)
    assert derive_known_at("spread_open", KICKOFF) == KICKOFF - timedelta(hours=72)
    assert derive_known_at("spread", KICKOFF) == KICKOFF
    with pytest.raises(LeakageError, match="rolling state"):
        derive_known_at("home_score", KICKOFF)


def test_derive_rankings_uses_the_earliest_week_kickoff() -> None:
    earliest = KICKOFF - timedelta(hours=6)
    assert derive_known_at("rank", KICKOFF, week_earliest_kickoff=earliest) == earliest - timedelta(
        hours=1
    )
    assert derive_known_at("rank", KICKOFF) == KICKOFF - timedelta(hours=1)


def test_provider_time_wins_when_supplied() -> None:
    provider_time = KICKOFF - timedelta(hours=50)
    assert derive_known_at("spread_open", KICKOFF, provider_time=provider_time) == provider_time
    with pytest.raises(LeakageError, match="timezone-aware"):
        derive_known_at(
            "spread_open",
            KICKOFF,
            provider_time=datetime(2026, 11, 26, 12, 0),
        )


def test_article_and_rolling_fields_require_explicit_timestamps() -> None:
    with pytest.raises(LeakageError, match="published_at"):
        derive_known_at("citation", KICKOFF)
    with pytest.raises(LeakageError, match="rolling state"):
        derive_known_at("rest_days_away", KICKOFF)


def test_is_admitted_is_fail_closed() -> None:
    assert is_admitted("spread_open", KICKOFF - timedelta(hours=1), KICKOFF) is True
    assert is_admitted("spread_open", None, KICKOFF) is False
    assert is_admitted("spread_open", KICKOFF, KICKOFF) is False
    assert is_admitted("home_score", KICKOFF - timedelta(days=1), KICKOFF) is False
    assert is_admitted("unknown_field", KICKOFF - timedelta(days=1), KICKOFF) is False


def test_filter_fields_keeps_only_admissible_values() -> None:
    fields = {
        "spread_open": (-3.5, KICKOFF - timedelta(hours=72)),
        "weather": (18.0, KICKOFF - timedelta(hours=24)),
        "home_score": (31, KICKOFF),
        "rest_days_away": (4, None),
    }
    filtered = filter_fields(fields, KICKOFF, source="test")
    assert filtered == {"spread_open": -3.5, "weather": 18.0}


def test_assert_feature_row_raises_on_the_first_bad_field() -> None:
    good = {
        "spread_open": (-3.5, KICKOFF - timedelta(hours=72)),
        "weather": (18.0, KICKOFF - timedelta(hours=24)),
    }
    assert_feature_row(good, KICKOFF, source="test")

    with pytest.raises(LeakageError, match="no known_at"):
        assert_feature_row({"rest_days_away": (4, None)}, KICKOFF)
    with pytest.raises(LeakageError):
        assert_feature_row({"rest_days_away": (4, KICKOFF + timedelta(seconds=1))}, KICKOFF)


def test_policy_violation_is_logged(caplog) -> None:
    with caplog.at_level("WARNING", logger="cfb_upset.leakage"):
        with pytest.raises(LeakageError):
            admit("home_score", KICKOFF, KICKOFF, source="box-score-writer")
    assert "leakage violation" in caplog.text
    assert "box-score-writer" in caplog.text
