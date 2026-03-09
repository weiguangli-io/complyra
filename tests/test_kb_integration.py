"""Integration tests for KB management — testing multi-layer flows with mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Document, Tenant, TenantPolicy, User
from app.db.session import Base


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite DB with all tables for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    session = TestSession()
    yield session, TestSession
    session.close()


@pytest.fixture()
def _patch_session(db_session):
    """Patch SessionLocal so audit_db functions use the test DB."""
    _, TestSession = db_session
    with patch("app.db.audit_db.SessionLocal", TestSession):
        yield


@pytest.fixture()
def _seed(db_session, _patch_session):
    """Seed a tenant and user so FK constraints pass."""
    session, _ = db_session
    session.add(Tenant(tenant_id="t1", name="Test Tenant"))
    session.add(User(user_id="u1", username="alice", password_hash="hash", role="admin"))
    session.commit()


class TestIngestCreatesDocumentRecord:
    @patch("app.workers.ingest_worker._move_to_preview_storage", return_value="/data/previews/doc-1.pdf")
    @patch("app.workers.ingest_worker._count_pages", return_value=3)
    @patch("app.workers.ingest_worker.ingest_document_from_path", return_value=("doc-ingest-1", 7))
    def test_ingest_creates_document_record(self, mock_ingest, mock_pages, mock_move, _seed, tmp_path):
        from app.db.audit_db import create_ingest_job, get_document
        from app.workers.ingest_worker import process_ingest_job

        create_ingest_job(job_id="j1", tenant_id="t1", created_by="u1", filename="report.pdf")

        test_file = tmp_path / "report.pdf"
        test_file.write_text("fake pdf")

        result = process_ingest_job(
            job_id="j1",
            file_path=str(test_file),
            filename="report.pdf",
            tenant_id="t1",
        )

        assert result["status"] == "completed"
        assert result["document_id"] == "doc-ingest-1"
        assert result["chunks_indexed"] == 7

        doc = get_document("doc-ingest-1")
        assert doc is not None
        assert doc.tenant_id == "t1"
        assert doc.filename == "report.pdf"
        assert doc.chunk_count == 7


class TestDocumentCrudLifecycle:
    def test_document_crud_lifecycle(self, _seed):
        from app.db.audit_db import get_document
        from app.services.documents import (
            create_document,
            get_document_detail,
            list_tenant_documents,
            update_sensitivity,
        )

        # Create
        doc = create_document(
            document_id="doc-lc-1",
            tenant_id="t1",
            filename="lifecycle.pdf",
            file_size=512,
            page_count=2,
            chunk_count=4,
            created_by="u1",
        )
        assert doc.document_id == "doc-lc-1"
        assert doc.mime_type == "application/pdf"
        assert doc.sensitivity == "normal"

        # Read
        detail = get_document_detail("doc-lc-1", "t1")
        assert detail is not None
        assert detail.filename == "lifecycle.pdf"

        # Wrong tenant returns None
        assert get_document_detail("doc-lc-1", "t_other") is None

        # List
        docs, total = list_tenant_documents("t1")
        assert total == 1

        # Update
        updated = update_sensitivity("doc-lc-1", "t1", "restricted")
        assert updated is not None
        assert updated.sensitivity == "restricted"

        # Verify persistence
        reloaded = get_document("doc-lc-1")
        assert reloaded.sensitivity == "restricted"


class TestTenantPolicyAffectsApproval:
    def test_tenant_policy_affects_approval(self, _seed):
        from app.db.audit_db import create_document_record
        from app.services.approval_policy import (
            get_tenant_approval_mode,
            set_tenant_approval_mode,
            should_require_approval,
        )

        # Create documents with different sensitivities
        create_document_record(
            document_id="doc-normal",
            tenant_id="t1",
            filename="normal.pdf",
            mime_type="application/pdf",
            file_size=100,
            page_count=1,
            chunk_count=1,
            created_by="u1",
            sensitivity="normal",
        )
        create_document_record(
            document_id="doc-sensitive",
            tenant_id="t1",
            filename="sensitive.pdf",
            mime_type="application/pdf",
            file_size=100,
            page_count=1,
            chunk_count=1,
            created_by="u1",
            sensitivity="sensitive",
        )

        # Set policy to "sensitive" mode
        set_tenant_approval_mode("t1", "sensitive", "alice")
        assert get_tenant_approval_mode("t1") == "sensitive"

        # Normal doc -> no approval needed
        assert should_require_approval("t1", ["doc-normal"]) is False

        # Sensitive doc -> approval needed
        assert should_require_approval("t1", ["doc-sensitive"]) is True

        # Mixed -> approval needed (any sensitive triggers it)
        assert should_require_approval("t1", ["doc-normal", "doc-sensitive"]) is True

        # Change to "none" mode
        set_tenant_approval_mode("t1", "none", "alice")
        assert should_require_approval("t1", ["doc-sensitive"]) is False

        # Change to "all" mode
        set_tenant_approval_mode("t1", "all", "alice")
        assert should_require_approval("t1", ["doc-normal"]) is True
