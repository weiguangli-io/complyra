"""Tests for Document and TenantPolicy DAL functions (CRUD) in audit_db."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Document, TenantPolicy, Tenant, User
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
def _seed_tenant_and_user(_patch_session, db_session):
    """Seed a tenant and user so FK constraints pass."""
    session, _ = db_session
    session.add(Tenant(tenant_id="t1", name="Test Tenant"))
    session.add(User(user_id="u1", username="alice", password_hash="hash", role="admin"))
    session.commit()


class TestCreateDocumentRecord:
    def test_create_document_record(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record

        doc = create_document_record(
            document_id="doc-1",
            tenant_id="t1",
            filename="report.pdf",
            mime_type="application/pdf",
            file_size=1024,
            page_count=5,
            chunk_count=10,
            created_by="u1",
            storage_path="/data/previews/doc-1.pdf",
            sensitivity="sensitive",
        )
        assert doc.document_id == "doc-1"
        assert doc.tenant_id == "t1"
        assert doc.filename == "report.pdf"
        assert doc.mime_type == "application/pdf"
        assert doc.file_size == 1024
        assert doc.page_count == 5
        assert doc.chunk_count == 10
        assert doc.sensitivity == "sensitive"
        assert doc.storage_path == "/data/previews/doc-1.pdf"

    def test_create_document_defaults(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record

        doc = create_document_record(
            document_id="doc-2",
            tenant_id="t1",
            filename="notes.txt",
            mime_type="text/plain",
            file_size=100,
            page_count=0,
            chunk_count=1,
            created_by="u1",
        )
        assert doc.sensitivity == "normal"
        assert doc.status == "active"
        assert doc.approval_override is None
        assert doc.storage_path is None


class TestGetDocument:
    def test_get_document_found(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, get_document

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        result = get_document("doc-1")
        assert result is not None
        assert result.document_id == "doc-1"

    def test_get_document_not_found(self, _patch_session):
        from app.db.audit_db import get_document

        result = get_document("nonexistent")
        assert result is None


class TestListDocuments:
    def _seed_docs(self):
        from app.db.audit_db import create_document_record

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1", sensitivity="normal",
        )
        create_document_record(
            document_id="doc-2", tenant_id="t1", filename="b.pdf",
            mime_type="application/pdf", file_size=200, page_count=2,
            chunk_count=5, created_by="u1", sensitivity="sensitive",
        )
        create_document_record(
            document_id="doc-3", tenant_id="t1", filename="c.txt",
            mime_type="text/plain", file_size=50, page_count=0,
            chunk_count=1, created_by="u1", sensitivity="normal",
        )

    def test_list_documents_with_status_filter(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, list_documents_db, update_document_db

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        create_document_record(
            document_id="doc-2", tenant_id="t1", filename="b.pdf",
            mime_type="application/pdf", file_size=200, page_count=2,
            chunk_count=5, created_by="u1",
        )
        update_document_db(document_id="doc-2", status="deleted")

        docs, total = list_documents_db(tenant_id="t1", status="active")
        assert total == 1
        assert len(docs) == 1
        assert docs[0].document_id == "doc-1"

    def test_list_documents_with_sensitivity_filter(self, _seed_tenant_and_user):
        self._seed_docs()
        from app.db.audit_db import list_documents_db

        docs, total = list_documents_db(tenant_id="t1", sensitivity="sensitive")
        assert total == 1
        assert docs[0].document_id == "doc-2"

    def test_list_documents_pagination(self, _seed_tenant_and_user):
        self._seed_docs()
        from app.db.audit_db import list_documents_db

        docs, total = list_documents_db(tenant_id="t1", status="active", limit=2, offset=0)
        assert total == 3
        assert len(docs) == 2

        docs2, total2 = list_documents_db(tenant_id="t1", status="active", limit=2, offset=2)
        assert total2 == 3
        assert len(docs2) == 1


class TestUpdateDocument:
    def test_update_document_sensitivity(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, update_document_db

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        updated = update_document_db(document_id="doc-1", sensitivity="restricted")
        assert updated is not None
        assert updated.sensitivity == "restricted"

    def test_update_document_approval_override(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, update_document_db

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        updated = update_document_db(document_id="doc-1", approval_override="always")
        assert updated is not None
        assert updated.approval_override == "always"


class TestBulkUpdateDocuments:
    def test_bulk_update_documents(self, _seed_tenant_and_user):
        from app.db.audit_db import bulk_update_documents_db, create_document_record, get_document

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        create_document_record(
            document_id="doc-2", tenant_id="t1", filename="b.pdf",
            mime_type="application/pdf", file_size=200, page_count=2,
            chunk_count=5, created_by="u1",
        )

        count = bulk_update_documents_db(
            document_ids=["doc-1", "doc-2"], tenant_id="t1", sensitivity="restricted",
        )
        assert count == 2
        assert get_document("doc-1").sensitivity == "restricted"
        assert get_document("doc-2").sensitivity == "restricted"

    def test_bulk_update_wrong_tenant_returns_zero(self, _seed_tenant_and_user):
        from app.db.audit_db import bulk_update_documents_db, create_document_record

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        count = bulk_update_documents_db(
            document_ids=["doc-1"], tenant_id="t999", sensitivity="restricted",
        )
        assert count == 0


class TestDeleteDocument:
    def test_delete_document_soft(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, get_document, update_document_db

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        update_document_db(document_id="doc-1", status="deleted")
        doc = get_document("doc-1")
        assert doc.status == "deleted"


class TestGetDocumentsByIds:
    def test_get_documents_by_ids(self, _seed_tenant_and_user):
        from app.db.audit_db import create_document_record, get_documents_by_ids

        create_document_record(
            document_id="doc-1", tenant_id="t1", filename="a.pdf",
            mime_type="application/pdf", file_size=100, page_count=1,
            chunk_count=2, created_by="u1",
        )
        create_document_record(
            document_id="doc-2", tenant_id="t1", filename="b.pdf",
            mime_type="application/pdf", file_size=200, page_count=2,
            chunk_count=5, created_by="u1",
        )
        result = get_documents_by_ids(["doc-1", "doc-2"])
        assert len(result) == 2

    def test_get_documents_by_ids_empty(self, _patch_session):
        from app.db.audit_db import get_documents_by_ids

        result = get_documents_by_ids([])
        assert result == []


class TestTenantPolicy:
    def test_get_tenant_policy_found(self, _seed_tenant_and_user):
        from app.db.audit_db import get_tenant_policy, upsert_tenant_policy

        upsert_tenant_policy(tenant_id="t1", approval_mode="sensitive", updated_by="alice")
        policy = get_tenant_policy("t1")
        assert policy is not None
        assert policy.approval_mode == "sensitive"

    def test_get_tenant_policy_not_found(self, _patch_session):
        from app.db.audit_db import get_tenant_policy

        policy = get_tenant_policy("nonexistent")
        assert policy is None

    def test_upsert_tenant_policy_create(self, _seed_tenant_and_user):
        from app.db.audit_db import upsert_tenant_policy

        policy = upsert_tenant_policy(tenant_id="t1", approval_mode="all", updated_by="alice")
        assert policy.tenant_id == "t1"
        assert policy.approval_mode == "all"
        assert policy.updated_by == "alice"

    def test_upsert_tenant_policy_update(self, _seed_tenant_and_user):
        from app.db.audit_db import get_tenant_policy, upsert_tenant_policy

        upsert_tenant_policy(tenant_id="t1", approval_mode="all", updated_by="alice")
        upsert_tenant_policy(tenant_id="t1", approval_mode="none", updated_by="bob")
        policy = get_tenant_policy("t1")
        assert policy.approval_mode == "none"
        assert policy.updated_by == "bob"
