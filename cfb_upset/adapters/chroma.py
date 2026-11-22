"""Chroma citation index, tagged by embedding space.

Collections are named and tagged with ``{model, dim, instruction_template,
normalized}``. A query or upsert whose vector width differs from the configured
width fails before Chroma sees it, so a 4096-d Ollama collection can never be
queried with a 2560-d ARC vector.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cfb_upset.adapters.embeddings import EmbeddingProvider
from cfb_upset.config import get_settings
from cfb_upset.errors import ContractError

try:  # pragma: no cover - exercised by the skip path when the package is absent
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CitationChunk:
    chunk_id: str
    text: str
    spec_id: str
    evidence_id: str
    domain: str
    published_at: datetime | None = None
    known_at: datetime | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    distance: float | None
    metadata: dict[str, Any]


class ChromaCitationStore:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        *,
        path: str | Path | None = None,
        client: Any = None,
        instruction_template: str | None = None,
        normalized: bool = True,
    ) -> None:
        if chromadb is None and client is None:
            raise RuntimeError(
                "chromadb is not installed; install it in the canonical env or skip this test"
            )
        self.embedder = embedder
        self.model = embedder.model
        self.dim = embedder.dim
        self.instruction_template = (
            embedder.instruction_template if instruction_template is None else instruction_template
        )
        self.normalized = normalized
        if client is not None:
            self.client = client
        else:
            location = (
                Path(path).expanduser() if path is not None else Path(get_settings().chroma_path)
            )
            location.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(location))
        self.collection_name = _collection_name(self.model, self.dim, self.instruction_template)
        self.collection = self._get_collection()

    def _metadata(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "dim": self.dim,
            "instruction_template": self.instruction_template,
            "normalized": self.normalized,
        }

    def _get_collection(self) -> Any:
        collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata=self._metadata(),
        )
        existing = collection.metadata or {}
        for key, expected in self._metadata().items():
            if key in existing and existing[key] != expected:
                raise ContractError(
                    f"Chroma collection {self.collection_name!r} metadata mismatch for "
                    f"{key!r}: existing={existing[key]!r} expected={expected!r}"
                )
        return collection

    async def upsert(self, chunks: list[CitationChunk]) -> int:
        if not chunks:
            return 0
        result = await self.embedder.embed_documents([chunk.text for chunk in chunks])
        _assert_width(result.vectors, self.dim)
        metadatas = [_metadata_for(chunk) for chunk in chunks]
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=result.vectors,
            metadatas=metadatas,
        )
        return len(chunks)

    async def query(
        self,
        text: str,
        *,
        n_results: int = 3,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        result = await self.embedder.embed_query(text)
        _assert_width(result.vectors, self.dim)
        response = self.collection.query(
            query_embeddings=result.vectors,
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (response.get("ids") or [[]])[0]
        documents = (response.get("documents") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]
        retrieved: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids):
            retrieved.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    text=str(documents[index]) if index < len(documents) else "",
                    distance=float(distances[index]) if index < len(distances) else None,
                    metadata=dict(metadatas[index]) if index < len(metadatas) else {},
                )
            )
        return retrieved

    def count(self) -> int:
        return int(self.collection.count())

    def metadata(self) -> dict[str, Any]:
        return dict(self.collection.metadata or {})

    def delete_collection(self) -> None:
        self.client.delete_collection(self.collection_name)


def _assert_width(vectors: list[list[float]], expected: int) -> None:
    for vector in vectors:
        if len(vector) != expected:
            raise ContractError(
                f"vector width {len(vector)} != collection width {expected}; refusing to mix spaces"
            )


def _metadata_for(chunk: CitationChunk) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "spec_id": chunk.spec_id,
        "evidence_id": chunk.evidence_id,
        "domain": chunk.domain,
        "chunk_id": chunk.chunk_id,
    }
    if chunk.published_at is not None:
        metadata["published_at"] = chunk.published_at.isoformat()
    if chunk.known_at is not None:
        metadata["known_at"] = chunk.known_at.isoformat()
    return metadata


def _collection_name(model: str, dim: int, instruction_template: str) -> str:
    safe_model = re.sub(r"[^a-zA-Z0-9]+", "_", model).strip("_").lower()[:40]
    instruction_hash = hashlib.sha256(instruction_template.encode("utf-8")).hexdigest()[:8]
    return f"citation_chunks__{safe_model}__{dim}__{instruction_hash}"


__all__ = ["ChromaCitationStore", "CitationChunk", "RetrievedChunk"]
