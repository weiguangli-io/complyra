"""Tests for the Qdrant retrieval service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.retrieval import (
    _collection_has_named_vectors,
    _collection_has_sparse_vectors,
    delete_document,
    ensure_collection,
    get_qdrant_client,
    list_documents,
    search_chunks,
    upsert_chunks,
)


@pytest.fixture(autouse=True)
def clear_caches():
    get_qdrant_client.cache_clear()
    yield
    get_qdrant_client.cache_clear()


@pytest.fixture()
def mock_qdrant():
    with patch("app.services.retrieval.QdrantClient") as MockQdrant:
        client = MagicMock()
        MockQdrant.return_value = client
        yield client


@pytest.fixture()
def mock_embed():
    with patch("app.services.retrieval.embed_texts") as mock_et, \
         patch("app.services.retrieval.get_embedder") as mock_ge:
        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 384
        mock_ge.return_value = mock_provider
        mock_et.return_value = [[0.1] * 384]
        yield mock_et, mock_provider


class TestEnsureCollection:
    def test_creates_collection_when_not_exists(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = False
        ensure_collection()
        mock_qdrant.create_collection.assert_called_once()

    def test_skips_creation_when_exists_same_dim(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info
        ensure_collection()
        mock_qdrant.create_collection.assert_not_called()

    def test_warns_on_dimension_mismatch(self, mock_qdrant, mock_embed, caplog):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 1536
        mock_qdrant.get_collection.return_value = mock_info
        import logging
        with caplog.at_level(logging.WARNING):
            ensure_collection()
        assert "dimension" in caplog.text.lower() or "mismatch" in caplog.text.lower() or "Recreate" in caplog.text


class TestUpsertChunks:
    def test_upsert_returns_document_id(self, mock_qdrant, mock_embed):
        mock_embed_texts, _ = mock_embed
        mock_embed_texts.return_value = [[0.1] * 384, [0.2] * 384]
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        doc_id = upsert_chunks(["chunk1", "chunk2"], "test.pdf", "tenant1")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0
        mock_qdrant.upsert.assert_called_once()

    def test_upsert_passes_tenant_id_in_payload(self, mock_qdrant, mock_embed):
        mock_embed_texts, _ = mock_embed
        mock_embed_texts.return_value = [[0.1] * 384]
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        upsert_chunks(["chunk"], "file.txt", "my-tenant")
        call_args = mock_qdrant.upsert.call_args
        points = call_args[1]["points"]
        assert points[0].payload["tenant_id"] == "my-tenant"


class TestSearchChunks:
    def test_returns_matches(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        mock_result = MagicMock()
        mock_result.score = 0.95
        mock_result.payload = {"text": "hello", "source": "doc.pdf", "page_numbers": [1, 2]}
        mock_response = MagicMock()
        mock_response.points = [mock_result]
        mock_qdrant.query_points.return_value = mock_response

        results = search_chunks("query", 4, "tenant1")
        assert len(results) == 1
        assert results[0] == ("hello", 0.95, "doc.pdf", [1, 2], "")

    def test_handles_empty_payload(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        mock_result = MagicMock()
        mock_result.score = 0.5
        mock_result.payload = None
        mock_response = MagicMock()
        mock_response.points = [mock_result]
        mock_qdrant.query_points.return_value = mock_response

        results = search_chunks("query", 4, "tenant1")
        assert results[0] == ("", 0.5, "", [], "")

    def test_applies_tenant_filter(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info
        mock_response = MagicMock()
        mock_response.points = []
        mock_qdrant.query_points.return_value = mock_response

        search_chunks("query", 4, "special-tenant")
        call_args = mock_qdrant.query_points.call_args
        query_filter = call_args[1]["query_filter"]
        assert query_filter.must[0].match.value == "special-tenant"


# ── _collection_has_sparse_vectors ─────────────────────────────


class TestCollectionHasSparseVectors:
    def test_returns_true_when_sparse_config_present(self, mock_qdrant):
        mock_info = MagicMock()
        mock_info.config.params.sparse_vectors = {"sparse": MagicMock()}
        mock_qdrant.get_collection.return_value = mock_info
        assert _collection_has_sparse_vectors() is True

    def test_returns_false_when_no_sparse_config(self, mock_qdrant):
        mock_info = MagicMock()
        mock_info.config.params.sparse_vectors = None
        mock_qdrant.get_collection.return_value = mock_info
        assert _collection_has_sparse_vectors() is False

    def test_returns_false_on_exception(self, mock_qdrant):
        mock_qdrant.get_collection.side_effect = Exception("not found")
        assert _collection_has_sparse_vectors() is False


class TestCollectionHasNamedVectors:
    def test_returns_true_when_dict_vectors(self, mock_qdrant):
        mock_info = MagicMock()
        mock_info.config.params.vectors = {"dense": MagicMock()}
        mock_qdrant.get_collection.return_value = mock_info
        assert _collection_has_named_vectors() is True

    def test_returns_false_when_flat_vectors(self, mock_qdrant):
        mock_info = MagicMock()
        mock_info.config.params.vectors = MagicMock(spec=[])  # Not a dict
        mock_qdrant.get_collection.return_value = mock_info
        assert _collection_has_named_vectors() is False

    def test_returns_false_on_exception(self, mock_qdrant):
        mock_qdrant.get_collection.side_effect = Exception("err")
        assert _collection_has_named_vectors() is False


# ── ensure_collection with hybrid search ───────────────────────


class TestEnsureCollectionHybrid:
    def test_creates_hybrid_collection(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", True)
        mock_qdrant.collection_exists.return_value = False
        ensure_collection()
        call_args = mock_qdrant.create_collection.call_args
        assert "sparse_vectors_config" in call_args[1]

    def test_creates_flat_collection(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", False)
        mock_qdrant.collection_exists.return_value = False
        ensure_collection()
        call_args = mock_qdrant.create_collection.call_args
        assert "sparse_vectors_config" not in call_args[1]

    def test_existing_collection_named_vectors_dim_check(self, mock_qdrant, mock_embed, monkeypatch):
        from qdrant_client.http import models as qmodels
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = {
            "dense": qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE)
        }
        mock_qdrant.get_collection.return_value = mock_info
        ensure_collection()
        mock_qdrant.create_collection.assert_not_called()


# ── upsert with named vectors and sparse ───────────────────────


class TestUpsertChunksHybrid:
    def test_upsert_with_named_vectors_and_sparse(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", True)
        mock_embed_texts, _ = mock_embed
        mock_embed_texts.return_value = [[0.1] * 384]

        # Collection exists with named vectors + sparse
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = {"dense": MagicMock(size=384)}
        mock_info.config.params.sparse_vectors = {"sparse": MagicMock()}
        mock_qdrant.get_collection.return_value = mock_info

        sparse_vec = MagicMock()
        with patch("app.services.sparse_embed.compute_sparse_vectors", return_value=[sparse_vec]):
            doc_id = upsert_chunks(["chunk1"], "test.pdf", "tenant1", page_numbers=[[1, 2]])
            assert isinstance(doc_id, str)
            points = mock_qdrant.upsert.call_args[1]["points"]
            assert isinstance(points[0].vector, dict)
            assert "dense" in points[0].vector
            assert "sparse" in points[0].vector
            assert points[0].payload["page_numbers"] == [1, 2]

    def test_upsert_flat_vectors(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", False)
        mock_embed_texts, _ = mock_embed
        mock_embed_texts.return_value = [[0.1] * 384]

        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = MagicMock(size=384, spec=[])
        mock_info.config.params.sparse_vectors = None
        mock_qdrant.get_collection.return_value = mock_info

        doc_id = upsert_chunks(["chunk1"], "test.pdf", "tenant1")
        points = mock_qdrant.upsert.call_args[1]["points"]
        assert isinstance(points[0].vector, list)


# ── list_documents ─────────────────────────────────────────────


class TestListDocuments:
    def test_lists_documents(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        point1 = MagicMock()
        point1.payload = {"document_id": "doc1", "source": "a.pdf"}
        point2 = MagicMock()
        point2.payload = {"document_id": "doc1", "source": "a.pdf"}
        point3 = MagicMock()
        point3.payload = {"document_id": "doc2", "source": "b.pdf"}
        mock_qdrant.scroll.return_value = ([point1, point2, point3], None)

        docs = list_documents("tenant1")
        assert len(docs) == 2
        doc_ids = {d["document_id"] for d in docs}
        assert doc_ids == {"doc1", "doc2"}
        # doc1 should have chunk_count=2
        doc1 = next(d for d in docs if d["document_id"] == "doc1")
        assert doc1["chunk_count"] == 2

    def test_lists_documents_pagination(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        point1 = MagicMock()
        point1.payload = {"document_id": "doc1", "source": "a.pdf"}
        point2 = MagicMock()
        point2.payload = {"document_id": "doc2", "source": "b.pdf"}

        # First page returns next_offset, second returns None
        mock_qdrant.scroll.side_effect = [
            ([point1], "next-offset"),
            ([point2], None),
        ]

        docs = list_documents("tenant1")
        assert len(docs) == 2
        assert mock_qdrant.scroll.call_count == 2

    def test_lists_documents_empty_payload(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info

        point = MagicMock()
        point.payload = None
        mock_qdrant.scroll.return_value = ([point], None)

        docs = list_documents("tenant1")
        assert len(docs) == 1
        assert docs[0]["document_id"] == ""


# ── delete_document ────────────────────────────────────────────


class TestDeleteDocument:
    def test_deletes_existing_document(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info
        mock_qdrant.count.return_value = MagicMock(count=3)

        count = delete_document("doc1", "tenant1")
        assert count == 3
        mock_qdrant.delete.assert_called_once()

    def test_deletes_no_matching_docs(self, mock_qdrant, mock_embed):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 384
        mock_qdrant.get_collection.return_value = mock_info
        mock_qdrant.count.return_value = MagicMock(count=0)

        count = delete_document("doc1", "tenant1")
        assert count == 0
        mock_qdrant.delete.assert_not_called()


# ── search_chunks hybrid ──────────────────────────────────────


class TestSearchChunksHybrid:
    def test_hybrid_search(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", True)
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = {"dense": MagicMock(size=384)}
        mock_info.config.params.sparse_vectors = {"sparse": MagicMock()}
        mock_qdrant.get_collection.return_value = mock_info

        mock_result = MagicMock()
        mock_result.score = 0.9
        mock_result.payload = {"text": "hybrid result", "source": "doc.pdf", "page_numbers": [1]}
        mock_response = MagicMock()
        mock_response.points = [mock_result]
        mock_qdrant.query_points.return_value = mock_response

        sparse_vec = MagicMock()
        with patch("app.services.sparse_embed.compute_sparse_vectors", return_value=[sparse_vec]):
            results = search_chunks("query", 4, "tenant1")
            assert len(results) == 1
            assert results[0][0] == "hybrid result"

    def test_dense_only_named_vectors(self, mock_qdrant, mock_embed, monkeypatch):
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", False)
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = {"dense": MagicMock(size=384)}
        mock_info.config.params.sparse_vectors = None
        mock_qdrant.get_collection.return_value = mock_info

        mock_response = MagicMock()
        mock_response.points = []
        mock_qdrant.query_points.return_value = mock_response

        search_chunks("query", 4, "tenant1")
        call_args = mock_qdrant.query_points.call_args
        assert call_args[1].get("using") == "dense"
