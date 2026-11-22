"""Identifiers, canonical JSON, hashing, and clocks."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from cfb_upset.ids import (
    FrozenClock,
    SystemClock,
    canonical_json,
    monotonic_ms,
    new_ulid,
    sha256_hex,
    stable_hash,
)

NOW = datetime(2026, 11, 22, 20, 0, tzinfo=UTC)
ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_new_ulid_shape_and_uniqueness() -> None:
    clock = FrozenClock(NOW)
    values = {new_ulid(clock) for _ in range(20)}

    assert len(values) == 20
    assert all(ULID_PATTERN.match(value) for value in values)


def test_new_ulid_timestamp_prefix_sorts_by_time() -> None:
    early = new_ulid(FrozenClock(NOW))
    later = new_ulid(FrozenClock(NOW + timedelta(seconds=1)))

    assert early[:10] < later[:10]


def test_frozen_clock_requires_aware_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 11, 22, 20, 0))


def test_frozen_clock_advances() -> None:
    clock = FrozenClock(NOW)
    clock.advance(90)
    assert clock.now() == NOW + timedelta(seconds=90)
    assert clock.now().tzinfo is UTC


def test_system_clock_is_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [2, 3]}) == '{"a":[2,3],"b":1}'


def test_canonical_json_serialises_datetimes_and_models() -> None:
    payload = {"when": NOW, "nested": {"value": 1}}
    assert canonical_json(payload) == '{"nested":{"value":1},"when":"2026-11-22T20:00:00+00:00"}'


def test_sha256_hex_known_vectors() -> None:
    assert sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex(b"abc") == sha256_hex("abc")


def test_stable_hash_is_order_independent_and_value_sensitive() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}
    different = {"a": 1, "b": 3}

    assert stable_hash(left) == stable_hash(right)
    assert stable_hash(left) != stable_hash(different)
    assert len(stable_hash(left)) == 64


def test_monotonic_ms_increases() -> None:
    first = monotonic_ms()
    second = monotonic_ms()
    assert second >= first
