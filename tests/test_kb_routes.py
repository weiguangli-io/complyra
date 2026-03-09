"""Tests for the Knowledge Base document and tenant policy routes."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_doc(**overrides):
    """Helper to create a mock Document object."""
    defaults = dict(
        document_id="doc-1",
        tenant_id="t1",
        filename="report.pdf",
        mime_type="application/pdf",
        file_size=1024,
        page_count=5,
        chunk_count=10,
        sensitivity="normal",
        status="active",
        approval_override=None,
        created_by="u1",
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )
    defaults.update(overrides)
    doc = MagicMock()
    for k, v in defaults.items():
        setattr(doc, k, v)
    return doc


class TestGetDocuments:
    @patch("app.api.routes.documents.list_tenant_documents")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_list_documents_returns_paginated_list(self, mock_tenant, mock_roles, mock_list):
        from app.api.routes.documents import get_documents

        doc1 = _make_doc(document_id="doc-1")
        doc2 = _make_doc(document_id="doc-2")
        mock_list.return_value = ([doc1, doc2], 2)

        result = get_documents(
            status="active", sensitivity=None, limit=100, offset=0,
            tenant_id="t1", user={"username": "admin", "role": "admin"},
        )
        assert result.total == 2
        assert len(result.items) == 2
        assert result.items[0].document_id == "doc-1"

    @patch("app.api.routes.documents.list_tenant_documents")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_list_documents_with_filters(self, mock_tenant, mock_roles, mock_list):
        from app.api.routes.documents import get_documents

        doc = _make_doc(sensitivity="sensitive")
        mock_list.return_value = ([doc], 1)

        result = get_documents(
            status="active", sensitivity="sensitive", limit=50, offset=0,
            tenant_id="t1", user={"username": "admin", "role": "admin"},
        )
        assert result.total == 1
        mock_list.assert_called_once_with(
            "t1", status="active", sensitivity="sensitive", limit=50, offset=0,
        )


class TestGetSingleDocument:
    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_get_single_document(self, mock_tenant, mock_roles, mock_detail):
        from app.api.routes.documents import get_document

        mock_detail.return_value = _make_doc()
        result = get_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.document_id == "doc-1"

    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_get_document_not_found(self, mock_tenant, mock_roles, mock_detail):
        from app.api.routes.documents import get_document

        mock_detail.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestUpdateDocument:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.update_document_fields")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_update_document_sensitivity(self, mock_tenant, mock_roles, mock_update, mock_log):
        from app.api.routes.documents import update_document
        from app.models.schemas import DocumentUpdateRequest

        mock_update.return_value = _make_doc(sensitivity="restricted")
        payload = DocumentUpdateRequest(sensitivity="restricted")

        result = update_document(
            document_id="doc-1",
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.sensitivity == "restricted"
        mock_log.assert_called_once()

    @patch("app.api.routes.documents.update_document_fields")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_update_document_not_found(self, mock_tenant, mock_roles, mock_update):
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


class TestRemoveDocument:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.delete_document")
    @patch("app.db.audit_db.update_document_db")
    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_delete_document(self, mock_tenant, mock_roles, mock_detail, mock_db_update, mock_del, mock_log):
        from app.api.routes.documents import remove_document

        mock_detail.return_value = _make_doc()
        mock_del.return_value = 5

        result = remove_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result["document_id"] == "doc-1"
        assert result["deleted_chunks"] == 5
        mock_log.assert_called_once()

    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_delete_document_not_found(self, mock_tenant, mock_roles, mock_detail):
        from app.api.routes.documents import remove_document

        mock_detail.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            remove_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestBulkOperation:
    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.bulk_delete_documents")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_bulk_delete(self, mock_tenant, mock_roles, mock_bulk_del, mock_log):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        mock_bulk_del.return_value = 3
        payload = DocumentBulkRequest(document_ids=["d1", "d2", "d3"], action="delete")

        result = bulk_operation(
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.affected == 3

    @patch("app.api.routes.documents.log_event")
    @patch("app.api.routes.documents.bulk_update_sensitivity")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_bulk_update_sensitivity(self, mock_tenant, mock_roles, mock_bulk_upd, mock_log):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        mock_bulk_upd.return_value = 2
        payload = DocumentBulkRequest(
            document_ids=["d1", "d2"], action="update_sensitivity", sensitivity="restricted",
        )

        result = bulk_operation(
            payload=payload,
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.affected == 2

    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_bulk_missing_sensitivity(self, mock_tenant, mock_roles):
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        payload = DocumentBulkRequest(
            document_ids=["d1"], action="update_sensitivity", sensitivity=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            bulk_operation(
                payload=payload,
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 400


class TestPreviewDocument:
    @patch("app.api.routes.documents.settings")
    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.get_preview_path")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_preview_document_pdf(self, mock_tenant, mock_roles, mock_preview, mock_detail, mock_settings, tmp_path):
        from app.api.routes.documents import preview_document

        test_file = tmp_path / "doc-1.pdf"
        test_file.write_text("fake pdf")

        mock_preview.return_value = test_file
        mock_detail.return_value = _make_doc(mime_type="application/pdf")
        mock_settings.document_preview_storage_path = str(tmp_path)

        result = preview_document(
            document_id="doc-1",
            tenant_id="t1",
            user={"username": "admin", "role": "admin"},
        )
        assert result.media_type == "application/pdf"

    @patch("app.api.routes.documents.get_preview_path")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_preview_not_found(self, mock_tenant, mock_roles, mock_preview):
        from app.api.routes.documents import preview_document

        mock_preview.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            preview_document(
                document_id="nonexistent",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404

    @patch("app.api.routes.documents.settings")
    @patch("app.api.routes.documents.get_document_detail")
    @patch("app.api.routes.documents.get_preview_path")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_preview_path_traversal_blocked(self, mock_tenant, mock_roles, mock_preview, mock_detail, mock_settings, tmp_path):
        from app.api.routes.documents import preview_document
        from pathlib import Path

        # Provide a path outside the preview root
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text("secret")

        mock_preview.return_value = outside_file
        mock_detail.return_value = _make_doc()
        mock_settings.document_preview_storage_path = str(tmp_path / "previews")

        with pytest.raises(HTTPException) as exc_info:
            preview_document(
                document_id="doc-1",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 403


class TestTenantPolicyRoutes:
    @patch("app.db.audit_db.get_tenant_policy")
    @patch("app.api.routes.tenants.require_roles")
    def test_get_tenant_policy(self, mock_roles, mock_get_policy):
        from app.api.routes.tenants import get_policy

        mock_policy = MagicMock()
        mock_policy.tenant_id = "t1"
        mock_policy.approval_mode = "sensitive"
        mock_policy.updated_at = datetime(2025, 1, 1)
        mock_policy.updated_by = "admin"
        mock_get_policy.return_value = mock_policy

        result = get_policy(
            tenant_id="t1",
            _current_user={"username": "admin", "role": "admin"},
        )
        assert result.approval_mode == "sensitive"

    @patch("app.api.routes.tenants.log_event")
    @patch("app.api.routes.tenants.set_tenant_approval_mode")
    @patch("app.api.routes.tenants.require_roles")
    def test_update_tenant_policy(self, mock_roles, mock_set, mock_log):
        from app.api.routes.tenants import update_policy
        from app.models.schemas import TenantPolicyUpdateRequest

        mock_policy = MagicMock()
        mock_policy.tenant_id = "t1"
        mock_policy.approval_mode = "none"
        mock_policy.updated_at = datetime(2025, 1, 1)
        mock_policy.updated_by = "admin"
        mock_set.return_value = mock_policy

        payload = TenantPolicyUpdateRequest(approval_mode="none")
        result = update_policy(
            tenant_id="t1",
            payload=payload,
            current_user={"username": "admin", "role": "admin"},
        )
        assert result.approval_mode == "none"
        mock_log.assert_called_once()
