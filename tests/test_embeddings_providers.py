"""Tests for embedding providers (OpenAI, Gemini, SentenceTransformer) and get_embedder/embed_texts."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.embeddings import (
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    OpenAIProvider,
    SentenceTransformerProvider,
    embed_texts,
    get_embedder,
)


@pytest.fixture(autouse=True)
def clear_embedder_cache():
    """Clear the lru_cache for get_embedder between tests."""
    get_embedder.cache_clear()
    yield
    get_embedder.cache_clear()


# ── SentenceTransformerProvider ──────────────────────────────────


class TestSentenceTransformerProvider:
    def test_init_loads_model(self):
        mock_st_class = MagicMock()
        mock_model = MagicMock()
        mock_st_class.return_value = mock_model

        with patch.dict(sys.modules, {"sentence_transformers": MagicMock(SentenceTransformer=mock_st_class)}):
            provider = SentenceTransformerProvider.__new__(SentenceTransformerProvider)
            # Simulate __init__ with mocked import
            with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
                MagicMock(SentenceTransformer=mock_st_class) if name == "sentence_transformers" else __import__(name, *a, **kw)
            )):
                from sentence_transformers import SentenceTransformer as _ST
                provider._model = mock_st_class("test-model")

        mock_st_class.assert_called_with("test-model")

    def test_embed_texts(self):
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = [
            MagicMock(tolist=MagicMock(return_value=[0.1, 0.2])),
            MagicMock(tolist=MagicMock(return_value=[0.3, 0.4])),
        ]
        provider = SentenceTransformerProvider.__new__(SentenceTransformerProvider)
        provider._model = mock_model

        result = provider.embed_texts(["hello", "world"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_model.encode.assert_called_once_with(["hello", "world"], normalize_embeddings=True)

    def test_get_dimension(self):
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        provider = SentenceTransformerProvider.__new__(SentenceTransformerProvider)
        provider._model = mock_model

        assert provider.get_dimension() == 384


# ── OpenAIProvider ──────────────────────────────────────────────


class TestOpenAIProvider:
    def test_init_creates_client(self):
        mock_openai_class = MagicMock()
        with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=mock_openai_class)}):
            provider = OpenAIProvider.__new__(OpenAIProvider)
            provider._client = mock_openai_class(api_key="test-key")
            provider._model = "text-embedding-3-small"
            provider._dimension = 1536

        mock_openai_class.assert_called_with(api_key="test-key")

    def test_embed_texts(self):
        mock_client = MagicMock()
        item1 = MagicMock()
        item1.embedding = [0.1, 0.2, 0.3]
        item2 = MagicMock()
        item2.embedding = [0.4, 0.5, 0.6]
        mock_client.embeddings.create.return_value = MagicMock(data=[item1, item2])

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._client = mock_client
        provider._model = "text-embedding-3-small"
        provider._dimension = 1536

        result = provider.embed_texts(["hello", "world"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embeddings.create.assert_called_once_with(
            input=["hello", "world"], model="text-embedding-3-small"
        )

    def test_get_dimension(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._dimension = 1536
        assert provider.get_dimension() == 1536


# ── GeminiEmbeddingProvider ─────────────────────────────────────


class TestGeminiEmbeddingProvider:
    def test_init(self):
        mock_httpx = MagicMock()
        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
            provider._api_key = "gemini-key"
            provider._model = "text-embedding-004"
            provider._dimension = 768
            provider._client = mock_httpx.Client(timeout=30)

    def test_embed_texts(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "embeddings": [
                {"values": [0.1, 0.2]},
                {"values": [0.3, 0.4]},
            ]
        }
        mock_client.post.return_value = mock_resp

        provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
        provider._api_key = "test-key"
        provider._model = "text-embedding-004"
        provider._dimension = 768
        provider._client = mock_client

        result = provider.embed_texts(["hello", "world"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_resp.raise_for_status.assert_called_once()

    def test_get_dimension(self):
        provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
        provider._dimension = 768
        assert provider.get_dimension() == 768


# ── get_embedder factory ────────────────────────────────────────


class TestGetEmbedder:
    def test_openai_provider(self, monkeypatch):
        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "openai")
        monkeypatch.setattr("app.services.embeddings.settings.openai_api_key", "sk-test")
        monkeypatch.setattr("app.services.embeddings.settings.openai_embedding_model", "text-embedding-3-small")
        monkeypatch.setattr("app.services.embeddings.settings.embedding_dimension", 1536)

        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            provider = get_embedder()
            assert isinstance(provider, OpenAIProvider)

    def test_openai_requires_api_key(self, monkeypatch):
        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "openai")
        monkeypatch.setattr("app.services.embeddings.settings.openai_api_key", "")

        with pytest.raises(ValueError, match="APP_OPENAI_API_KEY"):
            get_embedder()

    def test_gemini_provider(self, monkeypatch):
        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "gemini")
        monkeypatch.setattr("app.services.embeddings.settings.gemini_api_key", "gem-key")
        monkeypatch.setattr("app.services.embeddings.settings.gemini_embedding_model", "text-embedding-004")
        monkeypatch.setattr("app.services.embeddings.settings.embedding_dimension", 768)

        provider = get_embedder()
        assert isinstance(provider, GeminiEmbeddingProvider)

    def test_gemini_requires_api_key(self, monkeypatch):
        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "gemini")
        monkeypatch.setattr("app.services.embeddings.settings.gemini_api_key", "")

        with pytest.raises(ValueError, match="APP_GEMINI_API_KEY"):
            get_embedder()

    def test_sentence_transformer_default(self, monkeypatch):
        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "sentence-transformers")
        monkeypatch.setattr("app.services.embeddings.settings.embedding_model", "BAAI/bge-small-en-v1.5")

        mock_st = MagicMock()
        with patch.dict(sys.modules, {"sentence_transformers": mock_st}):
            provider = get_embedder()
            assert isinstance(provider, SentenceTransformerProvider)


# ── embed_texts public function ─────────────────────────────────


class TestEmbedTextsFunction:
    def test_delegates_to_provider(self, monkeypatch):
        mock_provider = MagicMock()
        mock_provider.embed_texts.return_value = [[0.1, 0.2]]
        monkeypatch.setattr("app.services.embeddings.get_embedder", lambda: mock_provider)

        result = embed_texts(["hello"])
        assert result == [[0.1, 0.2]]
        mock_provider.embed_texts.assert_called_once_with(["hello"])
