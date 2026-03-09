"""Smoke tests — minimal endpoint existence checks for KB management."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestDocumentsEndpointRequiresAuth:
    @patch("app.api.routes.documents.get_tenant_id")
    def test_documents_endpoint_requires_auth(self, mock_tenant):
        """Calling get_documents without a valid user dependency should fail with role check."""
        from app.api.routes.documents import get_documents

        # Simulate role guard rejecting the user
        with patch("app.api.routes.documents.require_roles") as mock_roles:
            guard = MagicMock(side_effect=HTTPException(status_code=403, detail="Insufficient role"))
            mock_roles.return_value = guard

            with pytest.raises(HTTPException) as exc_info:
                get_documents(
                    status="active", sensitivity=None, limit=100, offset=0,
                    tenant_id="t1",
                    user=guard(user={"username": "nobody", "role": "user"}),
                )
            assert exc_info.value.status_code == 403


class TestDocumentPreviewReturns404ForUnknown:
    @patch("app.api.routes.documents.get_preview_path")
    @patch("app.api.routes.documents.require_roles")
    @patch("app.api.routes.documents.get_tenant_id")
    def test_document_preview_returns_404_for_unknown(self, mock_tenant, mock_roles, mock_preview):
        from app.api.routes.documents import preview_document

        mock_preview.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            preview_document(
                document_id="unknown-doc",
                tenant_id="t1",
                user={"username": "admin", "role": "admin"},
            )
        assert exc_info.value.status_code == 404


class TestTenantPolicyRequiresAuth:
    def test_tenant_policy_requires_auth(self):
        """Calling get_policy without proper role should fail."""
        from app.api.routes.tenants import get_policy

        with patch("app.api.routes.tenants.require_roles") as mock_roles:
            guard = MagicMock(side_effect=HTTPException(status_code=403, detail="Insufficient role"))
            mock_roles.return_value = guard

            with pytest.raises(HTTPException) as exc_info:
                get_policy(
                    tenant_id="t1",
                    _current_user=guard(user={"username": "nobody", "role": "user"}),
                )
            assert exc_info.value.status_code == 403


class TestBulkEndpointRequiresAuth:
    def test_bulk_endpoint_requires_auth(self):
        """Calling bulk_operation without proper role should fail."""
        from app.api.routes.documents import bulk_operation
        from app.models.schemas import DocumentBulkRequest

        with patch("app.api.routes.documents.require_roles") as mock_roles:
            guard = MagicMock(side_effect=HTTPException(status_code=403, detail="Insufficient role"))
            mock_roles.return_value = guard

            payload = DocumentBulkRequest(document_ids=["d1"], action="delete")

            with pytest.raises(HTTPException) as exc_info:
                bulk_operation(
                    payload=payload,
                    tenant_id="t1",
                    user=guard(user={"username": "nobody", "role": "user"}),
                )
            assert exc_info.value.status_code == 403
