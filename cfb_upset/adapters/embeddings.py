"""Embedding adapters: Ollama (4096-d primary), ARC (2560-d optional), hashing.

One collection belongs to exactly one embedding space. Every response's vector
width is asserted against the configured dimension; a mismatch raises rather
than silently mixing spaces. The hashing embedder is deterministic and exists
only for offline tests.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.errors import ContractError
from cfb_upset.ids import Clock, SystemClock

_EMBED_DIMS = {"ollama": 4096, "arc": 2560, "hashing": 256}


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dim: int
    usage: dict[str, int] = field(default_factory=dict)
    normalized: bool = True

    @property
    def count(self) -> int:
        return len(self.vectors)


class EmbeddingProvider(Protocol):
    model: str
    dim: int
    instruction_template: str
    normalized: bool

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult: ...

    async def embed_query(self, text: str) -> EmbeddingResult: ...


class HashingEmbedder:
    """Deterministic feature-hashing embedder for tests and offline fallback."""

    normalized = True

    def __init__(self, dim: int = 256, *, model: str | None = None) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self.dim = dim
        self.model = model or f"hashing-{dim}"
        self.instruction_template = ""

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        return self._embed(texts)

    async def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed([text])

    def _embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vector(text) for text in texts],
            model=self.model,
            dim=self.dim,
            usage={"prompt_tokens": sum(_token_count(text) for text in texts)},
            normalized=True,
        )

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dim
            sign = 1.0 if (value >> 8) & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


class EmbeddingsClient:
    """OpenAI-compatible ``/embeddings`` client with width assertions."""

    normalized = True

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        backend: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        instruction_template: str | None = None,
        clock: Clock | None = None,
        batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self.backend = (backend or settings.embed_backend).lower()
        if self.backend not in _EMBED_DIMS:
            raise ValueError(f"unknown embedding backend {self.backend!r}")
        if self.backend == "hashing":
            raise ValueError("use HashingEmbedder for the hashing backend")
        if self.backend == "ollama":
            self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
            self.api_key = api_key
            self.model = model or settings.ollama_embed_model
            self.dim = dim or _EMBED_DIMS["ollama"]
        else:
            self.base_url = (base_url or settings.vt_arc_base_url).rstrip("/")
            self.api_key = api_key if api_key is not None else settings.arc_embed_key
            self.model = model or settings.arc_embed_model
            self.dim = dim or _EMBED_DIMS["arc"]
        self.instruction_template = (
            settings.embed_instruction_template
            if instruction_template is None
            else instruction_template
        )
        self.clock = clock or SystemClock()
        self.batch_size = batch_size or settings.embed_batch_size
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider=self.backend)
            self._owns_transport = True
        return self._transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        return await self.embed(texts, instruction=None)

    async def embed_query(self, text: str) -> EmbeddingResult:
        return await self.embed([text], instruction=self.instruction_template or None)

    async def embed(
        self,
        texts: list[str],
        *,
        instruction: str | None = None,
    ) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self.model, dim=self.dim)
        vectors: list[list[float]] = []
        usage = {"prompt_tokens": 0, "total_tokens": 0}
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            inputs = [_apply_instruction(text, instruction) for text in batch]
            response = await self._transport_or_default().post(
                f"{self.base_url}/embeddings",
                payload={"model": self.model, "input": inputs},
                headers=self._headers(),
            )
            if response.status_code != 200:
                raise ContractError(
                    f"{self.backend} embeddings returned HTTP {response.status_code}"
                )
            body = response.json()
            batch_vectors = _vectors_from(body)
            if len(batch_vectors) != len(batch):
                raise ContractError(
                    f"embeddings returned {len(batch_vectors)} vectors for {len(batch)} inputs"
                )
            vectors.extend(batch_vectors)
            batch_usage = body.get("usage") or {}
            usage["prompt_tokens"] += int(
                batch_usage.get("prompt_tokens") or batch_usage.get("input_tokens") or 0
            )
            usage["total_tokens"] += int(
                batch_usage.get("total_tokens")
                or batch_usage.get("prompt_tokens")
                or batch_usage.get("input_tokens")
                or 0
            )
        for vector in vectors:
            if len(vector) != self.dim:
                raise ContractError(
                    f"embedding width {len(vector)} != configured {self.dim} "
                    f"for model {self.model!r}; refusing to mix vector spaces"
                )
        per_text_tokens = max(1, usage["prompt_tokens"] // max(1, len(texts)))
        usage["prompt_tokens"] = per_text_tokens * len(texts)
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            dim=self.dim,
            usage=usage,
            normalized=True,
        )


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _apply_instruction(text: str, instruction: str | None) -> str:
    if not instruction:
        return text
    if "{text}" in instruction:
        return instruction.format(text=text)
    return f"{instruction}\n{text}"


def _vectors_from(body: dict[str, Any]) -> list[list[float]]:
    if isinstance(body.get("data"), list):
        items = sorted(body["data"], key=lambda item: item.get("index", 0))
        return [[float(value) for value in item["embedding"]] for item in items]
    if isinstance(body.get("embeddings"), list):
        return [[float(value) for value in vector] for vector in body["embeddings"]]
    if isinstance(body.get("embedding"), list):
        return [[float(value) for value in body["embedding"]]]
    raise ContractError("embedding response has no vectors")


def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "EmbeddingsClient",
    "HashingEmbedder",
    "vector_norm",
]
