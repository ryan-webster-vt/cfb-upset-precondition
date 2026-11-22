"""Content-addressed evidence snapshots (gzip + SHA-256).

The database stores the pointer, hash, and provenance. The raw text lives at
``data/evidence/<hash>.txt.gz`` so a citation can be re-read and verified even
after the source page changes. Writes are deterministic: the gzip mtime is
zero, so the same bytes always produce the same file.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cfb_upset.config import get_settings
from cfb_upset.ids import Clock, SystemClock, sha256_hex


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    source_url: str | None
    domain: str
    title: str | None
    published_at: datetime | None
    fetched_at: datetime
    content_hash: str
    snapshot_path: str | None
    kind: str
    created_at: datetime


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_id: str
    content_hash: str
    snapshot_path: str
    kind: str
    fetched_at: datetime
    deduplicated: bool

    def to_record(
        self,
        *,
        source_url: str | None,
        domain: str,
        title: str | None,
        published_at: datetime | None,
        created_at: datetime,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=self.evidence_id,
            source_url=source_url,
            domain=domain,
            title=title,
            published_at=published_at,
            fetched_at=self.fetched_at,
            content_hash=self.content_hash,
            snapshot_path=self.snapshot_path,
            kind=self.kind,
            created_at=created_at,
        )


class EvidenceStore:
    """Write, read, and verify gzip snapshots beneath one root directory."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.root = (
            Path(root).expanduser() if root is not None else Path(get_settings().evidence_path)
        )
        self.clock = clock or SystemClock()

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        content: str | bytes,
        *,
        kind: str,
        fetched_at: datetime | None = None,
        evidence_id: str | None = None,
    ) -> EvidenceSnapshot:
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = sha256_hex(data)
        filename = f"{digest}.txt.gz"
        path = self.root / filename
        self._ensure_root()
        deduplicated = path.exists()
        if not deduplicated:
            compressed = gzip.compress(data, mtime=0)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(compressed)
            temporary.replace(path)
        return EvidenceSnapshot(
            evidence_id=evidence_id or f"ev-{digest[:24]}",
            content_hash=digest,
            snapshot_path=filename,
            kind=kind,
            fetched_at=fetched_at or self.clock.now(),
            deduplicated=deduplicated,
        )

    def path_for(self, snapshot_path_or_hash: str) -> Path:
        name = snapshot_path_or_hash
        if not name.endswith(".txt.gz"):
            name = f"{name}.txt.gz"
        return self.root / Path(name).name

    def read(self, snapshot_path_or_hash: str) -> bytes:
        path = self.path_for(snapshot_path_or_hash)
        return gzip.decompress(path.read_bytes())

    def read_text(self, snapshot_path_or_hash: str) -> str:
        return self.read(snapshot_path_or_hash).decode("utf-8")

    def verify(self, snapshot_path_or_hash: str, expected_hash: str) -> bool:
        path = self.path_for(snapshot_path_or_hash)
        if not path.exists():
            return False
        return sha256_hex(gzip.decompress(path.read_bytes())) == expected_hash

    def verify_record(self, record: EvidenceRecord) -> bool:
        if not record.snapshot_path:
            return False
        return self.verify(record.snapshot_path, record.content_hash)
