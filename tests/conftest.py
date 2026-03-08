"""Shared test fixtures for the Complyra test suite."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_ollama(monkeypatch):
    """Mock Ollama HTTP calls so tests run without a live Ollama instance."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "mocked LLM answer"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response

    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)
    return mock_client


@pytest.fixture()
def mock_qdrant(monkeypatch):
    """Mock Qdrant client so tests run without a live Qdrant instance."""
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True

    mock_search_result = MagicMock()
    mock_search_result.score = 0.95
    mock_search_result.payload = {
        "text": "mocked chunk text",
        "source": "test.pdf",
        "tenant_id": "default",
        "page_numbers": [1],
    }
    mock_client.search.return_value = [mock_search_result]

    monkeypatch.setattr(
        "app.services.retrieval.get_qdrant_client", lambda: mock_client
    )
    return mock_client


@pytest.fixture()
def mock_embedder(monkeypatch):
    """Mock the embedding provider for unit tests."""

    class FakeProvider:
        def embed_texts(self, texts):
            return [[0.1] * 384 for _ in texts]

        def get_dimension(self):
            return 384

    fake = FakeProvider()
    monkeypatch.setattr("app.services.embeddings.get_embedder", lambda: fake)
    monkeypatch.setattr("app.services.retrieval.get_embedder", lambda: fake)
    return fake
