"""Tests for the documents API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


class TestGetDocuments:
    @patch("app.api.routes.documents.list_documents")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_returns_document_list(self, mock_tenant, mock_roles, mock_list):
        from app.api.routes.documents import get_documents

        mock_list.return_value = [
            {"document_id": "doc-1", "source": "report.pdf", "chunk_count": 5},
            {"document_id": "doc-2", "source": "guide.txt", "chunk_count": 3},
        ]

        result = get_documents(tenant_id="t1", user={"username": "admin", "role": "admin"})
        assert len(result) == 2
        assert result[0].document_id == "doc-1"
        assert result[0].filename == "report.pdf"
        assert result[0].chunk_count == 5
        assert result[1].document_id == "doc-2"

    @patch("app.api.routes.documents.list_documents")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_returns_empty_list(self, mock_tenant, mock_roles, mock_list):
        from app.api.routes.documents import get_documents

        mock_list.return_value = []
        result = get_documents(tenant_id="t1", user={"username": "admin", "role": "admin"})
        assert result == []


class TestRemoveDocument:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.delete_document")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_deletes_and_returns_count(self, mock_tenant, mock_roles, mock_delete, mock_log):
        from app.api.routes.documents import remove_document

        mock_delete.return_value = 5

        result = remove_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result["document_id"] == "doc-1"
        assert result["deleted_chunks"] == 5
        mock_log.assert_called_once()

    @patch("app.api.routes.documents.delete_document")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_returns_404_when_not_found(self, mock_tenant, mock_roles, mock_delete):
        from app.api.routes.documents import remove_document

        mock_delete.return_value = 0

        with pytest.raises(HTTPException) as exc_info:
            remove_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()
