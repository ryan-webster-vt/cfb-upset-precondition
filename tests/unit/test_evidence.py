"""Evidence snapshots: deterministic gzip, hashing, dedupe, and verification."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cfb_upset.store.evidence import EvidenceStore


def test_snapshot_is_content_addressed_and_deterministic(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    first = store.write("same bytes", kind="article")
    second = store.write("same bytes", kind="article")
    assert first.content_hash == second.content_hash
    assert first.snapshot_path == second.snapshot_path
    assert not first.deduplicated
    assert second.deduplicated
    assert store.read_text(first.content_hash) == "same bytes"
    assert store.verify(first.snapshot_path, first.content_hash)
    assert not store.verify(first.snapshot_path, "0" * 64)


def test_gzip_bytes_are_stable(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    snapshot = store.write("stable", kind="note")
    bytes_one = store.path_for(snapshot.snapshot_path).read_bytes()
    store.write("stable", kind="note")
    bytes_two = store.path_for(snapshot.snapshot_path).read_bytes()
    assert bytes_one == bytes_two


def test_record_round_trip_keeps_provenance(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    snapshot = store.write("body", kind="article")
    created = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    record = snapshot.to_record(
        source_url="https://www.espn.com/story",
        domain="espn.com",
        title="Story",
        published_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        created_at=created,
    )
    assert record.content_hash == snapshot.content_hash
    assert store.verify_record(record)
    assert record.created_at == created
