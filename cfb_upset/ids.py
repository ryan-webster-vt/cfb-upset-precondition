"""Deterministic identifiers, hashing, canonical JSON, and UTC clocks.

All hashes and cache keys in the project flow through this module so that
"same inputs -> same key" is a single, testable statement.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol


class Clock(Protocol):
    """Minimal clock protocol so tests can travel in time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC datetime."""


class SystemClock:
    """Production clock: timezone-aware UTC only."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test clock that returns a fixed instant (or advances only when told to)."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._instant += timedelta(seconds=seconds)


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(clock: Clock | None = None) -> str:
    """Return a 26-character Crockford-base32 ULID.

    The first 10 characters are a 48-bit millisecond timestamp; the remaining
    16 are 80 random bits. ULIDs sort lexicographically by creation time, which
    makes run/event traces easy to order without a database sequence.
    """

    clock = clock or SystemClock()
    timestamp_ms = int(clock.now().timestamp() * 1000)
    random_bits = int.from_bytes(os.urandom(10), "big")

    chars = ["0"] * 26
    for index in range(9, -1, -1):
        chars[index] = _CROCKFORD[timestamp_ms & 0x1F]
        timestamp_ms >>= 5
    for index in range(25, 9, -1):
        chars[index] = _CROCKFORD[random_bits & 0x1F]
        random_bits >>= 5
    return "".join(chars)


def canonical_json(value: Any) -> str:
    """Serialize ``value`` deterministically (sorted keys, compact separators).

    Datetimes are emitted in ISO-8601 form and non-JSON-native objects fall back
    to ``str``; callers that need a different coercion should convert first.
    """

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):  # Enum
        return value.value
    return str(value)


def sha256_hex(value: str | bytes) -> str:
    """Return the lowercase SHA-256 hex digest of text or bytes."""

    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def stable_hash(value: Any) -> str:
    """Hash an arbitrary JSON-compatible value via canonical JSON."""

    return sha256_hex(canonical_json(value))


def monotonic_ms() -> float:
    """Monotonic milliseconds for latency measurements (never wall-clock)."""

    return time.perf_counter() * 1000.0
