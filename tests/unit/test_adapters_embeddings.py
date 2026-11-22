"""Embedding adapters: deterministic hashing, batching, and width assertions."""

from __future__ import annotations

import json

import pytest

from cfb_upset.adapters.embeddings import (
    EmbeddingResult,
    EmbeddingsClient,
    HashingEmbedder,
    vector_norm,
)
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.errors import ContractError


def _embedding_body(vectors: list[list[float]], *, indices: list[int] | None = None) -> dict:
    order = indices or list(range(len(vectors)))
    return {
        "data": [{"index": index, "embedding": vectors[index]} for index in order],
        "usage": {"prompt_tokens": 9, "total_tokens": 9},
    }


def _client(transport: FixtureTransport, **overrides) -> EmbeddingsClient:
    options = {
        "backend": "ollama",
        "base_url": "https://embed.example",
        "model": "test-embed",
        "dim": 4,
        "api_key": "test-key",
        "batch_size": 8,
    }
    options.update(overrides)
    return EmbeddingsClient(transport, **options)


async def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(dim=32)
    first = await embedder.embed_documents(["short rest", "short rest", "long travel"])
    second = await embedder.embed_documents(["short rest"])
    assert first.count == 3
    assert first.dim == 32
    assert first.vectors[0] == first.vectors[1]
    assert first.vectors[0] == second.vectors[0]
    assert first.vectors[0] != first.vectors[2]
    assert vector_norm(first.vectors[0]) == pytest.approx(1.0)
    assert len(first.vectors[0]) == 32


async def test_hashing_embedder_handles_empty_and_empty_text() -> None:
    embedder = HashingEmbedder(dim=8)
    assert (await embedder.embed_documents([])).vectors == []
    vector = (await embedder.embed_documents([""])).vectors[0]
    assert vector[0] == pytest.approx(1.0)
    assert len(vector) == 8


def test_hashing_embedder_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError):
        HashingEmbedder(dim=0)


async def test_embeddings_client_sorts_by_index_and_checks_width() -> None:
    vectors = [
        [0.1, 0.0, 0.0, 0.0],
        [0.0, 0.2, 0.0, 0.0],
        [0.0, 0.0, 0.3, 0.0],
    ]
    transport = FixtureTransport().add("/embeddings", _embedding_body(vectors, indices=[2, 0, 1]))
    result = await _client(transport).embed_documents(["a", "b", "c"])
    assert result.count == 3
    assert result.dim == 4
    assert result.vectors[0][0] == pytest.approx(0.1)
    assert result.vectors[1][1] == pytest.approx(0.2)
    assert result.vectors[2][2] == pytest.approx(0.3)
    assert result.normalized is True


async def test_embeddings_client_applies_the_query_instruction_only() -> None:
    vectors = [[1.0, 0.0, 0.0, 0.0]]
    transport = FixtureTransport().add("/embeddings", _embedding_body(vectors))
    client = _client(transport, instruction_template="query: {text}")
    await client.embed_query("short rest")
    assert transport.calls[0].payload["input"] == ["query: short rest"]

    await client.embed_documents(["short rest"])
    assert transport.calls[1].payload["input"] == ["short rest"]


async def test_embeddings_client_batches_requests() -> None:
    transport = FixtureTransport().add("/embeddings", _embedding_body([[1.0, 0.0, 0.0, 0.0]]))
    client = _client(transport, batch_size=1)
    result = await client.embed_documents(["a", "b"])
    assert result.count == 2
    assert len(transport.calls) == 2


async def test_embedding_width_mismatch_is_refused() -> None:
    transport = FixtureTransport().add("/embeddings", _embedding_body([[0.1, 0.2, 0.3]]))
    with pytest.raises(ContractError, match="width 3 != configured 4"):
        await _client(transport).embed_documents(["a"])


async def test_embedding_count_mismatch_is_refused() -> None:
    transport = FixtureTransport().add("/embeddings", _embedding_body([[0.1, 0.0, 0.0, 0.0]]))
    with pytest.raises(ContractError, match="1 vectors for 2 inputs"):
        await _client(transport).embed_documents(["a", "b"])


async def test_empty_embeddings_request_does_no_work() -> None:
    transport = FixtureTransport()
    result = await _client(transport).embed_documents([])
    assert result.count == 0
    assert transport.calls == []


async def test_non_200_embeddings_response_is_a_contract_error() -> None:
    transport = FixtureTransport().add(
        "/embeddings", {"error": "context too long"}, status_code=400
    )
    with pytest.raises(ContractError, match="HTTP 400"):
        await _client(transport).embed_documents(["a"])


def test_hashing_backend_must_use_the_test_embedder() -> None:
    with pytest.raises(ValueError, match="use HashingEmbedder"):
        EmbeddingsClient(FixtureTransport(), backend="hashing")
    with pytest.raises(ValueError, match="unknown embedding backend"):
        EmbeddingsClient(FixtureTransport(), backend="mystery")


async def test_response_shape_variants() -> None:
    from cfb_upset.adapters.embeddings import _vectors_from

    assert _vectors_from({"embeddings": [[1.0], [2.0]]}) == [[1.0], [2.0]]
    assert _vectors_from({"embedding": [1.0, 2.0]}) == [[1.0, 2.0]]
    with pytest.raises(ContractError, match="no vectors"):
        _vectors_from({})


def test_embedding_result_count_property() -> None:
    result = EmbeddingResult(vectors=[[1.0], [2.0]], model="m", dim=1)
    assert result.count == 2
    assert json.dumps(result.usage) == "{}"
