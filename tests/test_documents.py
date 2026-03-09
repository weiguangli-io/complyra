"""Tests for the documents API routes (rewritten for KB management system)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGetDocuments:
    @patch("app.api.routes.documents.list_tenant_documents")
    def test_returns_document_list(self, mock_list):
        from app.api.routes.documents import get_documents

        mock_doc = MagicMock()
        mock_doc.document_id = "doc-1"
        mock_doc.tenant_id = "t1"
        mock_doc.filename = "report.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.file_size = 1024
        mock_doc.page_count = 5
        mock_doc.chunk_count = 10
        mock_doc.sensitivity = "normal"
        mock_doc.status = "active"
        mock_doc.approval_override = None
        mock_doc.created_by = "admin"
        mock_doc.created_at = "2024-01-01T00:00:00"
        mock_doc.updated_at = "2024-01-01T00:00:00"

        mock_list.return_value = ([mock_doc], 1)

        result = get_documents(
            status="active", sensitivity=None, limit=100, offset=0,
            tenant_id="t1", user={"username": "admin", "role": "admin"},
        )
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].document_id == "doc-1"

    @patch("app.api.routes.documents.list_tenant_documents")
    def test_returns_empty_list(self, mock_list):
        from app.api.routes.documents import get_documents

        mock_list.return_value = ([], 0)
        result = get_documents(
            status="active", sensitivity=None, limit=100, offset=0,
            tenant_id="t1", user={"username": "admin", "role": "admin"},
        )
        assert result.total == 0
        assert result.items == []


class TestGetDocumentDetail:
    @patch("app.api.routes.documents.get_document_detail")
    def test_returns_document(self, mock_get):
        from app.api.routes.documents import get_document

        mock_doc = MagicMock()
        mock_doc.document_id = "doc-1"
        mock_doc.tenant_id = "t1"
        mock_doc.filename = "report.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.file_size = 1024
        mock_doc.page_count = 5
        mock_doc.chunk_count = 10
        mock_doc.sensitivity = "normal"
        mock_doc.status = "active"
        mock_doc.approval_override = None
        mock_doc.created_by = "admin"
        mock_doc.created_at = "2024-01-01T00:00:00"
        mock_doc.updated_at = "2024-01-01T00:00:00"
        mock_get.return_value = mock_doc

        result = get_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.document_id == "doc-1"

    @patch("app.api.routes.documents.get_document_detail")
    def test_raises_404_when_not_found(self, mock_get):
        from app.api.routes.documents import get_document

        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestRemoveDocument:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.delete_document")
    @patch("app.db.audit_db.update_document_db")
    @patch("app.api.routes.documents.get_document_detail")
    def test_deletes_and_returns_count(self, mock_detail, mock_update, mock_delete, mock_log):
        from app.api.routes.documents import remove_document

        mock_doc = MagicMock()
        mock_detail.return_value = mock_doc
        mock_delete.return_value = 5

        result = remove_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result["document_id"] == "doc-1"
        assert result["deleted_chunks"] == 5
        mock_log.assert_called_once()

    @patch("app.api.routes.documents.get_document_detail")
    def test_returns_404_when_not_found(self, mock_detail):
        from app.api.routes.documents import remove_document

        mock_detail.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            remove_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestUpdateDocument:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.update_document_fields")
    def test_update_document(self, mock_update, mock_log):
        from app.api.routes.documents import update_document
        from app.models.schemas import DocumentUpdateRequest

        mock_doc = MagicMock()
        mock_doc.document_id = "doc-1"
        mock_doc.tenant_id = "t1"
        mock_doc.filename = "report.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.file_size = 1024
        mock_doc.page_count = 5
        mock_doc.chunk_count = 10
        mock_doc.sensitivity = "sensitive"
        mock_doc.status = "active"
        mock_doc.approval_override = "always"
        mock_doc.created_by = "admin"
        mock_doc.created_at = "2024-01-01T00:00:00"
        mock_doc.updated_at = "2024-01-01T00:00:00"
        mock_update.return_value = mock_doc

        payload = DocumentUpdateRequest(sensitivity="sensitive", approval_override="always")
        result = update_document(
            document_id="doc-1",
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.sensitivity == "sensitive"
        mock_log.assert_called_once()

    @patch("app.api.routes.documents.update_document_fields")
    def test_update_document_not_found(self, mock_update):
        from app.api.routes.documents import update_document
        from app.models.schemas import DocumentUpdateRequest

        mock_update.return_value = None
        payload = DocumentUpdateRequest(sensitivity="sensitive")

        with pytest.raises(HTTPException) as exc_info:
            update_document(
                document_id="nonexistent",
                payload=payload,
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestBulkOperation:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.bulk_delete_documents")
    def test_bulk_delete(self, mock_bulk_del, mock_log):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        mock_bulk_del.return_value = 2
        payload = DocumentBulkRequest(document_ids=["doc-1", "doc-2"], action="delete")

        result = bulk_operation(
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.affected == 2

    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.bulk_update_sensitivity")
    def test_bulk_update_sensitivity(self, mock_bulk, mock_log):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        mock_bulk.return_value = 3
        payload = DocumentBulkRequest(
            document_ids=["doc-1", "doc-2", "doc-3"],
            action="update_sensitivity",
            sensitivity="restricted",
        )

        result = bulk_operation(
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.affected == 3

    def test_bulk_unknown_action_rejected_by_schema(self):
        from pydantic import ValidationError
        from app.models.schemas import DocumentBulkRequest

        with pytest.raises(ValidationError):
            DocumentBulkRequest(document_ids=["doc-1"], action="unknown")

    def test_bulk_update_sensitivity_missing_field(self):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        payload = DocumentBulkRequest(document_ids=["doc-1"], action="update_sensitivity")

        with pytest.raises(HTTPException) as exc_info:
            bulk_operation(
                payload=payload,
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 400


class TestPreviewDocument:
    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.get_preview_path")
    def test_preview_not_available(self, mock_preview, mock_detail):
        from app.api.routes.documents import preview_document

        mock_preview.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            preview_document(
                document_id="doc-1",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestGetDocumentsLegacy:
    @patch("app.api.routes.documents.list_documents")
    def test_returns_legacy_format(self, mock_list):
        from app.api.routes.documents import get_documents_legacy

        mock_list.return_value = [
            {"document_id": "doc-1", "source": "report.pdf", "chunk_count": 5},
        ]

        result = get_documents_legacy(
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert len(result) == 1
        assert result[0].document_id == "doc-1"
        assert result[0].filename == "report.pdf"
