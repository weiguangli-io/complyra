from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import and_, func, select

from app.db.models import Approval, AuditLog, Document, IngestJob, Tenant, TenantPolicy, User, UserTenant
from app.db.session import Base, SessionLocal, engine


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_db() -> None:
    """Initialize schema in development mode. Production should use Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def insert_log(
    *,
    tenant_id: str,
    user: str,
    action: str,
    input_text: str,
    output_text: str,
    metadata: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                user=user,
                action=action,
                input_text=input_text,
                output_text=output_text,
                meta_json=metadata,
            )
        )
        db.commit()


def list_logs(*, tenant_ids: list[str], limit: int = 100) -> list[AuditLog]:
    with SessionLocal() as db:
        query = select(AuditLog).where(AuditLog.tenant_id.in_(tenant_ids)).order_by(AuditLog.id.desc()).limit(limit)
        return list(db.execute(query).scalars())


def search_logs(
    *,
    tenant_ids: list[str],
    username: Optional[str],
    action: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    limit: int,
) -> list[AuditLog]:
    with SessionLocal() as db:
        query = select(AuditLog).where(AuditLog.tenant_id.in_(tenant_ids))
        if username:
            query = query.where(AuditLog.user == username)
        if action:
            query = query.where(AuditLog.action == action)
        if start_time:
            query = query.where(AuditLog.timestamp >= start_time)
        if end_time:
            query = query.where(AuditLog.timestamp <= end_time)
        query = query.order_by(AuditLog.id.desc()).limit(limit)
        return list(db.execute(query).scalars())


def create_tenant(*, tenant_id: str, name: str) -> Tenant:
    with SessionLocal() as db:
        tenant = Tenant(tenant_id=tenant_id, name=name)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant


def list_tenants() -> list[Tenant]:
    with SessionLocal() as db:
        return list(db.execute(select(Tenant).order_by(Tenant.created_at.desc())).scalars())


def get_tenant(tenant_id: str) -> Optional[Tenant]:
    with SessionLocal() as db:
        return db.get(Tenant, tenant_id)


def create_user(
    *,
    user_id: str,
    username: str,
    password_hash: str,
    role: str,
    default_tenant_id: Optional[str],
) -> User:
    with SessionLocal() as db:
        user = User(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            role=role,
            default_tenant_id=default_tenant_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def get_user_by_username(username: str) -> Optional[User]:
    with SessionLocal() as db:
        return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def get_user_by_id(user_id: str) -> Optional[User]:
    with SessionLocal() as db:
        return db.get(User, user_id)


def list_users() -> list[User]:
    with SessionLocal() as db:
        return list(db.execute(select(User).order_by(User.created_at.desc())).scalars())


def assign_user_tenant(*, user_id: str, tenant_id: str) -> UserTenant:
    with SessionLocal() as db:
        existing = db.execute(
            select(UserTenant).where(and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if existing:
            return existing
        link = UserTenant(user_id=user_id, tenant_id=tenant_id)
        db.add(link)
        db.commit()
        db.refresh(link)
        return link


def list_user_tenants(user_id: str) -> list[UserTenant]:
    with SessionLocal() as db:
        return list(db.execute(select(UserTenant).where(UserTenant.user_id == user_id)).scalars())


def user_has_tenant(*, user_id: str, tenant_id: str) -> bool:
    with SessionLocal() as db:
        row = db.execute(
            select(UserTenant).where(and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id))
        ).scalar_one_or_none()
        return row is not None


def create_approval(
    *,
    approval_id: str,
    user_id: str,
    tenant_id: str,
    question: str,
    draft_answer: str,
) -> Approval:
    with SessionLocal() as db:
        approval = Approval(
            approval_id=approval_id,
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            draft_answer=draft_answer,
            status="pending",
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        return approval


def list_approvals(*, tenant_ids: list[str], status: Optional[str], limit: int) -> list[Approval]:
    with SessionLocal() as db:
        query = select(Approval).where(Approval.tenant_id.in_(tenant_ids))
        if status:
            query = query.where(Approval.status == status)
        query = query.order_by(Approval.created_at.desc()).limit(limit)
        return list(db.execute(query).scalars())


def get_approval(approval_id: str) -> Optional[Approval]:
    with SessionLocal() as db:
        return db.get(Approval, approval_id)


def update_approval(
    *,
    approval_id: str,
    status: str,
    decision_by: str,
    decision_note: str,
    final_answer: Optional[str],
) -> Optional[Approval]:
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if not approval:
            return None
        approval.status = status
        approval.decision_by = decision_by
        approval.decision_note = decision_note
        approval.decided_at = utcnow_naive()
        approval.final_answer = final_answer
        db.commit()
        db.refresh(approval)
        return approval


def create_ingest_job(*, job_id: str, tenant_id: str, created_by: str, filename: str) -> IngestJob:
    with SessionLocal() as db:
        job = IngestJob(job_id=job_id, tenant_id=tenant_id, created_by=created_by, filename=filename, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def update_ingest_job(
    *,
    job_id: str,
    status: str,
    chunks_indexed: int = 0,
    document_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[IngestJob]:
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
        if not job:
            return None
        job.status = status
        job.chunks_indexed = chunks_indexed
        job.document_id = document_id
        job.error_message = error_message
        job.updated_at = utcnow_naive()
        db.commit()
        db.refresh(job)
        return job


def get_ingest_job(job_id: str) -> Optional[IngestJob]:
    with SessionLocal() as db:
        return db.get(IngestJob, job_id)


def list_ingest_jobs(*, tenant_ids: list[str], limit: int) -> list[IngestJob]:
    with SessionLocal() as db:
        query = select(IngestJob).where(IngestJob.tenant_id.in_(tenant_ids)).order_by(IngestJob.created_at.desc()).limit(limit)
        return list(db.execute(query).scalars())


# ── Document CRUD ──────────────────────────────────────────────────────

def create_document_record(
    *,
    document_id: str,
    tenant_id: str,
    filename: str,
    mime_type: str,
    file_size: int,
    page_count: int,
    chunk_count: int,
    created_by: str,
    storage_path: str | None = None,
    sensitivity: str = "normal",
) -> Document:
    with SessionLocal() as db:
        doc = Document(
            document_id=document_id,
            tenant_id=tenant_id,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            page_count=page_count,
            chunk_count=chunk_count,
            created_by=created_by,
            storage_path=storage_path,
            sensitivity=sensitivity,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc


def get_document(document_id: str) -> Document | None:
    with SessionLocal() as db:
        return db.get(Document, document_id)


def list_documents_db(
    *,
    tenant_id: str,
    status: str | None = "active",
    sensitivity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Document], int]:
    with SessionLocal() as db:
        query = select(Document).where(Document.tenant_id == tenant_id)
        count_query = select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
        if status:
            query = query.where(Document.status == status)
            count_query = count_query.where(Document.status == status)
        if sensitivity:
            query = query.where(Document.sensitivity == sensitivity)
            count_query = count_query.where(Document.sensitivity == sensitivity)
        total = db.execute(count_query).scalar() or 0
        query = query.order_by(Document.created_at.desc()).offset(offset).limit(limit)
        docs = list(db.execute(query).scalars())
        return docs, total


def update_document_db(
    *,
    document_id: str,
    sensitivity: str | None = None,
    status: str | None = None,
    approval_override: str | None = "__unset__",
) -> Document | None:
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        if not doc:
            return None
        if sensitivity is not None:
            doc.sensitivity = sensitivity
        if status is not None:
            doc.status = status
        if approval_override != "__unset__":
            doc.approval_override = approval_override
        doc.updated_at = utcnow_naive()
        db.commit()
        db.refresh(doc)
        return doc


def bulk_update_documents_db(
    *,
    document_ids: list[str],
    tenant_id: str,
    sensitivity: str | None = None,
    status: str | None = None,
) -> int:
    with SessionLocal() as db:
        query = select(Document).where(
            and_(Document.document_id.in_(document_ids), Document.tenant_id == tenant_id)
        )
        docs = list(db.execute(query).scalars())
        for doc in docs:
            if sensitivity is not None:
                doc.sensitivity = sensitivity
            if status is not None:
                doc.status = status
            doc.updated_at = utcnow_naive()
        db.commit()
        return len(docs)


def get_documents_by_ids(document_ids: list[str]) -> list[Document]:
    if not document_ids:
        return []
    with SessionLocal() as db:
        query = select(Document).where(Document.document_id.in_(document_ids))
        return list(db.execute(query).scalars())


# ── TenantPolicy CRUD ──────────────────────────────────────────────────

def get_tenant_policy(tenant_id: str) -> TenantPolicy | None:
    with SessionLocal() as db:
        return db.get(TenantPolicy, tenant_id)


def upsert_tenant_policy(
    *,
    tenant_id: str,
    approval_mode: str,
    updated_by: str,
) -> TenantPolicy:
    with SessionLocal() as db:
        policy = db.get(TenantPolicy, tenant_id)
        if policy:
            policy.approval_mode = approval_mode
            policy.updated_by = updated_by
            policy.updated_at = utcnow_naive()
        else:
            policy = TenantPolicy(
                tenant_id=tenant_id,
                approval_mode=approval_mode,
                updated_by=updated_by,
            )
            db.add(policy)
        db.commit()
        db.refresh(policy)
        return policy


def ensure_default_seed(*, demo_username: str, demo_password_hash: str, default_tenant_id: str) -> None:
    with SessionLocal() as db:
        tenant = db.get(Tenant, default_tenant_id)
        if not tenant:
            tenant = Tenant(tenant_id=default_tenant_id, name="Default Tenant")
            db.add(tenant)

        user = db.execute(select(User).where(User.username == demo_username)).scalar_one_or_none()
        if not user:
            user_id = str(uuid4())
            user = User(
                user_id=user_id,
                username=demo_username,
                password_hash=demo_password_hash,
                role="admin",
                default_tenant_id=default_tenant_id,
            )
            db.add(user)
            db.add(UserTenant(user_id=user_id, tenant_id=default_tenant_id))

        db.commit()
