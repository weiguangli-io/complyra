from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    default_tenant_id: Mapped[Optional[str]] = mapped_column(String(128), ForeignKey("tenants.tenant_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)

    tenant_links = relationship("UserTenant", back_populates="user", cascade="all, delete-orphan")


class UserTenant(Base):
    __tablename__ = "user_tenants"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
        Index("ix_user_tenants_user_id", "user_id"),
        Index("ix_user_tenants_tenant_id", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="tenant_links")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_tenant_status", "tenant_id", "status"),
        Index("ix_approvals_user", "user_id"),
    )

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(128), ForeignKey("users.user_id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), ForeignKey("tenants.tenant_id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    draft_answer: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    decision_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_ts", "tenant_id", "timestamp"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[str] = mapped_column("metadata", Text, nullable=False)


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        Index("ix_ingest_jobs_tenant_created", "tenant_id", "created_at"),
        Index("ix_ingest_jobs_status", "status"),
    )

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), ForeignKey("tenants.tenant_id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), ForeignKey("users.user_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    chunks_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        Index("ix_documents_tenant_sensitivity", "tenant_id", "sensitivity"),
    )

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), ForeignKey("tenants.tenant_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    approval_override: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), ForeignKey("users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)


class TenantPolicy(Base):
    __tablename__ = "tenant_policies"

    tenant_id: Mapped[str] = mapped_column(String(128), ForeignKey("tenants.tenant_id"), primary_key=True)
    approval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow_naive, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
