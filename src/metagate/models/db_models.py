"""SQLAlchemy ORM models."""
from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, Text, Enum, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from ..database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class AuditAction(enum.Enum):
    """Audit action types for tracking operations."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"


class Principal(Base):
    """Principal - who is speaking."""
    __tablename__ = "principals"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    principal_key = Column(Text, unique=True, nullable=False)
    auth_subject = Column(Text, unique=True, nullable=False)
    principal_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Text, nullable=True)
    updated_by = Column(Text, nullable=True)

    bindings = relationship("Binding", back_populates="principal")
    api_keys = relationship("ApiKey", back_populates="principal")


class Profile(Base):
    """Profile - capabilities and policy constraints."""
    __tablename__ = "profiles"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    profile_key = Column(Text, unique=True, nullable=False)
    capabilities = Column(JSONType, nullable=False)
    policy = Column(JSONType, nullable=False)
    startup_sla_seconds = Column(Integer, default=120)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Text, nullable=True)
    updated_by = Column(Text, nullable=True)

    bindings = relationship("Binding", back_populates="profile")


class Manifest(Base):
    """Manifest - world description."""
    __tablename__ = "manifests"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    manifest_key = Column(Text, unique=True, nullable=False)
    deployment_key = Column(Text, default="default")
    environment = Column(JSONType, nullable=False)
    services = Column(JSONType, nullable=False)
    memory_map = Column(JSONType, nullable=False)
    polling = Column(JSONType, nullable=False)
    schemas = Column(JSONType, nullable=False)
    version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Text, nullable=True)
    updated_by = Column(Text, nullable=True)

    bindings = relationship("Binding", back_populates="manifest")


class Binding(Base):
    """Binding - ties principal to profile and manifest."""
    __tablename__ = "bindings"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    principal_id = Column(Uuid(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"))
    profile_id = Column(Uuid(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"))
    manifest_id = Column(Uuid(as_uuid=True), ForeignKey("manifests.id", ondelete="CASCADE"))
    overrides = Column(JSONType)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Text, nullable=True)
    updated_by = Column(Text, nullable=True)

    principal = relationship("Principal", back_populates="bindings")
    profile = relationship("Profile", back_populates="bindings")
    manifest = relationship("Manifest", back_populates="bindings")


class SecretRef(Base):
    """Secret reference - references only, never stores values."""
    __tablename__ = "secret_refs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    secret_key = Column(Text, unique=True, nullable=False)
    ref_kind = Column(Text, default="env")
    ref_name = Column(Text, nullable=False)
    ref_meta = Column(JSONType)
    status = Column(Text, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Text, nullable=True)
    updated_by = Column(Text, nullable=True)


class StartupSession(Base):
    """Startup session - bootstrap witness record."""
    __tablename__ = "startup_sessions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    deployment_key = Column(Text, default="default")
    subject_principal_key = Column(Text, nullable=False)
    component_key = Column(Text, nullable=False)
    profile_key = Column(Text, nullable=False)
    manifest_key = Column(Text, nullable=False)
    packet_etag = Column(Text, nullable=False)
    packet_hash_redacted = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    deadline_at = Column(DateTime(timezone=True))
    ready_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
    ready_payload = Column(JSONType)
    failure_payload = Column(JSONType)
    mirror_status = Column(Text, default="PENDING")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApiKey(Base):
    """API Key for authentication."""
    __tablename__ = "api_keys"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default")
    key_hash = Column(Text, unique=True, nullable=False)
    principal_id = Column(Uuid(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"))
    name = Column(Text, nullable=False)
    status = Column(Text, default="active")
    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Text, nullable=True)

    principal = relationship("Principal", back_populates="api_keys")


class AuditLog(Base):
    """Audit log for tracking security-sensitive operations.

    Records who did what, when, and on which resource. This provides
    an immutable accountability trail for security-sensitive changes.
    """
    __tablename__ = "audit_log"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_key = Column(Text, default="default", nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    action = Column(Text, nullable=False)
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Uuid(as_uuid=True), nullable=False)
    resource_key = Column(Text, nullable=True)
    actor_principal_key = Column(Text, nullable=False)
    actor_ip = Column(Text, nullable=True)
    actor_user_agent = Column(Text, nullable=True)
    changes = Column(JSONType, nullable=True)
    metadata_ = Column("metadata", JSONType, nullable=True)
