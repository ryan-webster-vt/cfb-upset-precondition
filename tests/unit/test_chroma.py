"""Chroma citation store: tagged collections, metadata, and space isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from cfb_upset.adapters.chroma import ChromaCitationStore, CitationChunk
from cfb_upset.adapters.embeddings import EmbeddingResult, HashingEmbedder
from cfb_upset.errors import ContractError

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class WrongWidthEmbedder:
    model = "hashing-32"
    dim = 32
    instruction_template = ""
    normalized = True

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[1.0] * 16 for _ in texts], model=self.model, dim=16)

    async def embed_query(self, text: str) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[1.0] * 16], model=self.model, dim=16)


def _chunks() -> list[CitationChunk]:
    return [
        CitationChunk(
            chunk_id="chunk-rest",
            text="Away teams on short rest allow more explosive plays.",
            spec_id="spec-short-rest",
            evidence_id="ev-1",
            domain="espn.com",
            published_at=NOW,
            known_at=NOW,
        ),
        CitationChunk(
            chunk_id="chunk-travel",
            text="Long travel and early kickoffs reduce performance.",
            spec_id="spec-travel",
            evidence_id="ev-2",
            domain="si.com",
        ),
    ]


async def test_round_trip_with_hashing_embedder(tmp_path: Path) -> None:
    embedder = HashingEmbedder(dim=32)
    store = ChromaCitationStore(embedder, path=tmp_path / "chroma")
    assert await store.upsert(_chunks()) == 2
    assert store.count() == 2

    metadata = store.metadata()
    assert metadata["model"] == embedder.model
    assert metadata["dim"] == 32
    assert metadata["instruction_template"] == ""
    assert metadata["normalized"] is True
    assert store.collection_name.startswith("citation_chunks__hashing_32__32__")

    hits = await store.query("short rest explosive plays", n_results=1)
    assert len(hits) == 1
    assert hits[0].chunk_id == "chunk-rest"
    assert hits[0].metadata["spec_id"] == "spec-short-rest"
    assert hits[0].metadata["known_at"] == NOW.isoformat()
    assert hits[0].distance is not None


async def test_query_filter_and_empty_upsert(tmp_path: Path) -> None:
    store = ChromaCitationStore(HashingEmbedder(dim=24), path=tmp_path / "chroma")
    assert await store.upsert([]) == 0
    await store.upsert(_chunks())
    hits = await store.query("travel", n_results=5, where={"domain": "si.com"})
    assert [hit.chunk_id for hit in hits] == ["chunk-travel"]


async def test_collections_are_reused_for_the_same_space(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    first = ChromaCitationStore(HashingEmbedder(dim=16), path=path)
    await first.upsert(_chunks()[:1])
    second = ChromaCitationStore(HashingEmbedder(dim=16), path=path)
    assert second.collection_name == first.collection_name
    assert second.count() == 1


async def test_different_models_use_different_collections(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    first = ChromaCitationStore(HashingEmbedder(dim=16), path=path)
    second = ChromaCitationStore(HashingEmbedder(dim=16, model="other-model"), path=path)
    assert first.collection_name != second.collection_name


async def test_width_mismatch_fails_before_chroma_accepts_it(tmp_path: Path) -> None:
    store = ChromaCitationStore(WrongWidthEmbedder(), path=tmp_path / "chroma")
    with pytest.raises(ContractError, match="width 16 != collection width 32"):
        await store.upsert(_chunks())
    assert store.count() == 0


async def test_negative_results_and_distance_metadata(tmp_path: Path) -> None:
    store = ChromaCitationStore(HashingEmbedder(dim=20), path=tmp_path / "chroma")
    await store.upsert(_chunks())
    hits = await store.query("not related at all", n_results=2)
    assert len(hits) == 2
    assert all(hit.distance is not None for hit in hits)
    assert {hit.metadata["chunk_id"] for hit in hits} == {"chunk-rest", "chunk-travel"}
