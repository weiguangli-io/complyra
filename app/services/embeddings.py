"""Pluggable embedding provider abstraction.

Supports SentenceTransformer (local BGE models) and OpenAI API embeddings.
Switch providers via the ``APP_EMBEDDING_PROVIDER`` environment variable.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import List

from langsmith import traceable

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Base class for embedding providers."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Encode a list of texts into embedding vectors."""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        ...


class SentenceTransformerProvider(EmbeddingProvider):
    """Local BGE/SentenceTransformer embeddings."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]

    def get_dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()


class OpenAIProvider(EmbeddingProvider):
    """OpenAI API embeddings (text-embedding-3-small, etc.)."""

    def __init__(self, api_key: str, model: str, dimension: int):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]

    def get_dimension(self) -> int:
        return self._dimension


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embedding API via REST (text-embedding-004, free tier)."""

    def __init__(self, api_key: str, model: str, dimension: int):
        import httpx

        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._client = httpx.Client(timeout=30)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:batchEmbedContents?key={self._api_key}"
        )
        requests = [
            {
                "model": f"models/{self._model}",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": self._dimension,
            }
            for t in texts
        ]
        resp = self._client.post(url, json={"requests": requests})
        resp.raise_for_status()
        return [e["values"] for e in resp.json()["embeddings"]]

    def get_dimension(self) -> int:
        return self._dimension


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    """Return a cached embedding provider instance based on configuration."""
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("APP_OPENAI_API_KEY is required when embedding_provider is 'openai'")
        logger.info(
            "Using OpenAI embedding provider: model=%s, dimension=%d",
            settings.openai_embedding_model,
            settings.embedding_dimension,
        )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimension=settings.embedding_dimension,
        )
    if settings.embedding_provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("APP_GEMINI_API_KEY is required when embedding_provider is 'gemini'")
        logger.info(
            "Using Gemini embedding provider: model=%s, dimension=%d",
            settings.gemini_embedding_model,
            settings.embedding_dimension,
        )
        return GeminiEmbeddingProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_embedding_model,
            dimension=settings.embedding_dimension,
        )
    logger.info("Using SentenceTransformer embedding provider: model=%s", settings.embedding_model)
    return SentenceTransformerProvider(settings.embedding_model)


@traceable(name="embed_texts", run_type="embedding")
def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using the configured provider."""
    import time
    from app.core.metrics import EMBEDDING_DURATION, EMBEDDING_TEXTS_PROCESSED

    provider = settings.embedding_provider
    start = time.perf_counter()
    result = get_embedder().embed_texts(texts)
    EMBEDDING_DURATION.labels(provider=provider).observe(time.perf_counter() - start)
    EMBEDDING_TEXTS_PROCESSED.labels(provider=provider).inc(len(texts))
    return result
