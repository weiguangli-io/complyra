"""Tests for the document service layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDetectMimeType:
    def test_detect_mime_type_pdf(self):
        from app.services.documents import detect_mime_type

        assert detect_mime_type("report.pdf") == "application/pdf"

    def test_detect_mime_type_txt(self):
        from app.services.documents import detect_mime_type

        assert detect_mime_type("notes.txt") == "text/plain"

    def test_detect_mime_type_png(self):
        from app.services.documents import detect_mime_type

        assert detect_mime_type("image.png") == "image/png"

    def test_detect_mime_type_unknown(self):
        from app.services.documents import detect_mime_type

        result = detect_mime_type("data.xyz_unknown_ext")
        assert result == "application/octet-stream"


class TestCreateDocument:
    @patch("app.services.documents._create_doc")
    def test_create_document_calls_dal(self, mock_create):
        from app.services.documents import create_document

        mock_doc = MagicMock()
        mock_create.return_value = mock_doc

        result = create_document(
            document_id="doc-1",
            tenant_id="t1",
            filename="report.pdf",
            file_size=1024,
            page_count=5,
            chunk_count=10,
            created_by="u1",
            storage_path="/data/previews/doc-1.pdf",
        )
        assert result is mock_doc
        mock_create.assert_called_once_with(
            document_id="doc-1",
            tenant_id="t1",
            filename="report.pdf",
            mime_type="application/pdf",
            file_size=1024,
            page_count=5,
            chunk_count=10,
            created_by="u1",
            storage_path="/data/previews/doc-1.pdf",
        )


class TestGetDocumentDetail:
    @patch("app.services.documents.get_document")
    def test_get_document_detail_correct_tenant(self, mock_get):
        from app.services.documents import get_document_detail

        mock_doc = MagicMock()
        mock_doc.tenant_id = "t1"
        mock_get.return_value = mock_doc

        result = get_document_detail("doc-1", "t1")
        assert result is mock_doc

    @patch("app.services.documents.get_document")
    def test_get_document_detail_wrong_tenant(self, mock_get):
        from app.services.documents import get_document_detail

        mock_doc = MagicMock()
        mock_doc.tenant_id = "t1"
        mock_get.return_value = mock_doc

        result = get_document_detail("doc-1", "t_other")
        assert result is None


class TestListTenantDocuments:
    @patch("app.services.documents.list_documents_db")
    def test_list_tenant_documents(self, mock_list):
        from app.services.documents import list_tenant_documents

        mock_list.return_value = ([MagicMock()], 1)
        docs, total = list_tenant_documents("t1", status="active", sensitivity="normal", limit=50, offset=10)
        assert total == 1
        assert len(docs) == 1
        mock_list.assert_called_once_with(
            tenant_id="t1", status="active", sensitivity="normal", limit=50, offset=10,
        )


class TestUpdateSensitivity:
    @patch("app.services.documents.update_document_db")
    @patch("app.services.documents.get_document")
    def test_update_sensitivity(self, mock_get, mock_update):
        from app.services.documents import update_sensitivity

        mock_doc = MagicMock()
        mock_doc.tenant_id = "t1"
        mock_get.return_value = mock_doc
        mock_update.return_value = MagicMock(sensitivity="sensitive")

        result = update_sensitivity("doc-1", "t1", "sensitive")
        assert result is not None
        mock_update.assert_called_once_with(document_id="doc-1", sensitivity="sensitive")

    @patch("app.services.documents.get_document")
    def test_update_sensitivity_wrong_tenant(self, mock_get):
        from app.services.documents import update_sensitivity

        mock_doc = MagicMock()
        mock_doc.tenant_id = "t1"
        mock_get.return_value = mock_doc

        result = update_sensitivity("doc-1", "t_other", "sensitive")
        assert result is None


class TestUpdateApprovalOverride:
    @patch("app.services.documents.update_document_db")
    @patch("app.services.documents.get_document")
    def test_update_approval_override(self, mock_get, mock_update):
        from app.services.documents import update_approval_override

        mock_doc = MagicMock()
        mock_doc.tenant_id = "t1"
        mock_get.return_value = mock_doc
        mock_update.return_value = MagicMock(approval_override="always")

        result = update_approval_override("doc-1", "t1", "always")
        assert result is not None
        mock_update.assert_called_once_with(document_id="doc-1", approval_override="always")


class TestBulkUpdateSensitivity:
    @patch("app.services.documents.bulk_update_documents_db")
    def test_bulk_update_sensitivity(self, mock_bulk):
        from app.services.documents import bulk_update_sensitivity

        mock_bulk.return_value = 3
        result = bulk_update_sensitivity(["doc-1", "doc-2", "doc-3"], "t1", "restricted")
        assert result == 3
        mock_bulk.assert_called_once_with(
            document_ids=["doc-1", "doc-2", "doc-3"], tenant_id="t1", sensitivity="restricted",
        )


class TestBulkDeleteDocuments:
    @patch("app.services.documents.delete_qdrant_doc")
    @patch("app.services.documents.bulk_update_documents_db")
    def test_bulk_delete_documents(self, mock_bulk, mock_qdrant_del):
        from app.services.documents import bulk_delete_documents

        mock_bulk.return_value = 2
        result = bulk_delete_documents(["doc-1", "doc-2"], "t1")
        assert result == 2
        mock_bulk.assert_called_once_with(
            document_ids=["doc-1", "doc-2"], tenant_id="t1", status="deleted",
        )
        assert mock_qdrant_del.call_count == 2


class TestGetPreviewPath:
    @patch("app.services.documents.get_document_detail")
    def test_get_preview_path_exists(self, mock_detail, tmp_path):
        from app.services.documents import get_preview_path

        # Create a real temp file
        test_file = tmp_path / "doc-1.pdf"
        test_file.write_text("fake pdf content")

        mock_doc = MagicMock()
        mock_doc.storage_path = str(test_file)
        mock_detail.return_value = mock_doc

        result = get_preview_path("doc-1", "t1")
        assert result is not None
        assert result == Path(str(test_file))

    @patch("app.services.documents.get_document_detail")
    def test_get_preview_path_no_storage(self, mock_detail):
        from app.services.documents import get_preview_path

        mock_doc = MagicMock()
        mock_doc.storage_path = None
        mock_detail.return_value = mock_doc

        result = get_preview_path("doc-1", "t1")
        assert result is None

    @patch("app.services.documents.get_document_detail")
    def test_get_preview_path_file_missing(self, mock_detail):
        from app.services.documents import get_preview_path

        mock_doc = MagicMock()
        mock_doc.storage_path = "/nonexistent/path/doc.pdf"
        mock_detail.return_value = mock_doc

        result = get_preview_path("doc-1", "t1")
        assert result is None
