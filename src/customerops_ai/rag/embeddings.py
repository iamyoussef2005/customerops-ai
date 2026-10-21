"""Explicit embedding boundary; batch and validate outputs before modifying the index."""

import math
from collections.abc import Sequence
from typing import Protocol

from openai import APIError, APITimeoutError, AsyncOpenAI

from customerops_ai.core.errors import AppError


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def validate_vectors(vectors: list[list[float]], count: int, dimensions: int) -> None:
    if len(vectors) != count or any(
        len(vector) != dimensions
        or not all(math.isfinite(value) for value in vector)
        or not any(value != 0 for value in vector)
        for vector in vectors
    ):
        raise AppError("embedding_invalid", "The embedding provider returned invalid vectors.", 502)


class OpenAIEmbeddings:
    def __init__(
        self, client: AsyncOpenAI, model: str, dimensions: int, batch_size: int = 16
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = list(texts[start : start + self.batch_size])
                response = await self.client.embeddings.create(
                    input=batch,
                    model=self.model,
                    dimensions=self.dimensions,
                    encoding_format="float",
                )
                if sorted(item.index for item in response.data) != list(range(len(batch))):
                    raise AppError(
                        "embedding_invalid", "The embedding provider returned invalid vectors.", 502
                    )
                rows = [
                    item.embedding for item in sorted(response.data, key=lambda item: item.index)
                ]
                validate_vectors(rows, len(batch), self.dimensions)
                vectors.extend(rows)
        except APITimeoutError as exc:
            raise AppError(
                "embedding_timeout", "Embedding generation timed out. Please retry.", 504
            ) from exc
        except APIError as exc:
            raise AppError(
                "embedding_unavailable", "The embedding provider is unavailable.", 503
            ) from exc
        return vectors
