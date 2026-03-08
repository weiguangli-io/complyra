"""Tests for the sparse embedding service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qdrant_client.http.models import SparseVector

from app.services.sparse_embed import compute_sparse_vectors, get_sparse_embedder


class TestGetSparseEmbedder:
    def test_creates_singleton(self):
        # Clear lru_cache before test
        get_sparse_embedder.cache_clear()

        mock_instance = MagicMock()
        mock_fastembed = MagicMock()
        mock_fastembed.SparseTextEmbedding.return_value = mock_instance

        import sys
        with patch.dict(sys.modules, {"fastembed": mock_fastembed}):
            result1 = get_sparse_embedder()
            result2 = get_sparse_embedder()

        assert result1 is result2
        mock_fastembed.SparseTextEmbedding.assert_called_once_with(model_name="Qdrant/bm25")

        # Clean up
        get_sparse_embedder.cache_clear()


class TestComputeSparseVectors:
    @patch("app.services.sparse_embed.get_sparse_embedder")
    def test_returns_sparse_vectors(self, mock_get_embedder):
        mock_embedding1 = MagicMock()
        mock_embedding1.indices.tolist.return_value = [0, 3, 7]
        mock_embedding1.values.tolist.return_value = [0.5, 0.3, 0.8]

        mock_embedding2 = MagicMock()
        mock_embedding2.indices.tolist.return_value = [1, 4]
        mock_embedding2.values.tolist.return_value = [0.2, 0.6]

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = iter([mock_embedding1, mock_embedding2])
        mock_get_embedder.return_value = mock_embedder

        results = compute_sparse_vectors(["text one", "text two"])

        assert len(results) == 2
        assert isinstance(results[0], SparseVector)
        assert results[0].indices == [0, 3, 7]
        assert results[0].values == [0.5, 0.3, 0.8]
        assert isinstance(results[1], SparseVector)
        assert results[1].indices == [1, 4]
        assert results[1].values == [0.2, 0.6]

    @patch("app.services.sparse_embed.get_sparse_embedder")
    def test_handles_empty_input(self, mock_get_embedder):
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = iter([])
        mock_get_embedder.return_value = mock_embedder

        results = compute_sparse_vectors([])
        assert results == []
