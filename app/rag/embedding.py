import asyncio
import hashlib
import math
import re
from typing import Protocol

import httpx

from app.core.config import Settings


class EmbeddingError(ConnectionError):
    """Safe provider errors mapped to temporarily_unavailable by the Tool boundary."""


def validate_vectors(vectors: object, count: int, dimension: int | None = None) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("embedding_invalid_response")
    result = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            or abs(v) > 3.4e38 for v in vector
        ):
            raise EmbeddingError("embedding_invalid_vector")
        dimension = dimension or len(vector)
        if len(vector) != dimension or not any(vector):
            raise EmbeddingError("embedding_dimension_or_zero_vector")
        result.append([float(v) for v in vector])
    return result


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbedding:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.model = settings.embedding_model or ""
        self.transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        s = self.settings
        if not (s.embedding_base_url and self.model and s.embedding_api_key
                and s.embedding_api_key.get_secret_value().strip()):
            raise EmbeddingError("embedding_not_configured")
        try:
            url = httpx.URL(s.embedding_base_url)
            if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment:
                raise ValueError("invalid_url")
        except (ValueError, httpx.InvalidURL):
            raise EmbeddingError("embedding_configuration_error") from None
        try:
            async with asyncio.timeout(s.embedding_timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport, timeout=s.embedding_timeout_seconds) as client:
                    response = await client.post(str(url).rstrip("/") + "/embeddings",
                        headers={"Authorization": "Bearer " + s.embedding_api_key.get_secret_value()},
                        json={"model": self.model, "input": texts, "encoding_format": "float"})
                    response.raise_for_status()
        except (TimeoutError, httpx.RequestError, httpx.HTTPStatusError):
            raise EmbeddingError("embedding_unavailable") from None
        try:
            payload = response.json()
            if payload.get("model", self.model) != self.model:
                raise ValueError("model_mismatch")
            rows = payload["data"]
            if not isinstance(rows, list) or any(type(row["index"]) is not int for row in rows):
                raise ValueError("invalid_index")
            rows = sorted(rows, key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError("invalid_indices")
            return validate_vectors([row["embedding"] for row in rows], len(texts), s.embedding_dim)
        except (KeyError, TypeError, AttributeError, ValueError, RecursionError):
            raise EmbeddingError("embedding_invalid_response") from None


class FakeEmbeddingProvider:
    """Deterministic signed character-bigram hashing, NOT a semantic model."""

    model = "fake-char-bigram-256-v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * 256  # Dimension is defined by this fake algorithm, not a guessed live model.
            compact = re.sub(r"\s+", "", text.lower())
            for token in [compact[i:i + 2] for i in range(max(1, len(compact) - 1))]:
                digest = hashlib.sha256(token.encode()).digest()
                vector[digest[0]] += 1 if digest[1] % 2 else -1
            vectors.append(vector)
        return validate_vectors(vectors, len(texts), 256)
