"""Audit logging service for MetaGate.

Provides functions to record security-sensitive operations in the audit_log table.
All admin operations (create, update, delete) on principals, profiles, manifests,
bindings, and secret references should be recorded.
"""
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import AuditLog, AuditAction
from ..logging import get_logger

logger = get_logger("metagate.audit")


async def record_audit(
    db: AsyncSession,
    *,
    action: str | AuditAction,
    resource_type: str,
    resource_id: UUID,
    actor_principal_key: str,
    tenant_key: str = "default",
    resource_key: str | None = None,
    actor_ip: str | None = None,
    actor_user_agent: str | None = None,
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an audit log entry for a security-sensitive operation.

    Args:
        db: Database session
        action: The action performed (CREATE, UPDATE, DELETE, etc.)
        resource_type: Type of resource (principal, profile, manifest, binding, secret_ref)
        resource_id: UUID of the affected resource
        actor_principal_key: Principal key of the user who performed the action
        tenant_key: Tenant context
        resource_key: Human-readable key of the resource (e.g., principal_key)
        actor_ip: IP address of the actor
        actor_user_agent: User agent string
        changes: Dict describing what changed (for updates: {field: {old: x, new: y}})
        metadata: Additional context about the operation

    Returns:
        The created AuditLog entry
    """
    if isinstance(action, AuditAction):
        action = action.value

    audit_entry = AuditLog(
        tenant_key=tenant_key,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_key=resource_key,
        actor_principal_key=actor_principal_key,
        actor_ip=actor_ip,
        actor_user_agent=actor_user_agent,
        changes=changes,
        metadata_=metadata,
    )

    db.add(audit_entry)

    logger.info(
        "audit_recorded",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        resource_key=resource_key,
        actor=actor_principal_key,
        tenant=tenant_key,
    )

    return audit_entry


def extract_request_info(request: Request | None) -> tuple[str | None, str | None]:
    """Extract IP and user agent from a request.

    Args:
        request: FastAPI request object (may be None)

    Returns:
        Tuple of (ip_address, user_agent)
    """
    if request is None:
        return None, None

    # Get IP address (consider X-Forwarded-For for proxied requests)
    ip = request.headers.get("x-forwarded-for")
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else None

    user_agent = request.headers.get("user-agent")

    return ip, user_agent


async def audit_create(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: UUID,
    resource_key: str,
    actor_principal_key: str,
    tenant_key: str = "default",
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a CREATE operation in the audit log."""
    ip, user_agent = extract_request_info(request)
    return await record_audit(
        db,
        action=AuditAction.CREATE,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_key=resource_key,
        actor_principal_key=actor_principal_key,
        tenant_key=tenant_key,
        actor_ip=ip,
        actor_user_agent=user_agent,
        metadata=metadata,
    )


async def audit_update(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: UUID,
    resource_key: str,
    actor_principal_key: str,
    changes: dict[str, Any],
    tenant_key: str = "default",
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an UPDATE operation in the audit log."""
    ip, user_agent = extract_request_info(request)
    return await record_audit(
        db,
        action=AuditAction.UPDATE,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_key=resource_key,
        actor_principal_key=actor_principal_key,
        tenant_key=tenant_key,
        actor_ip=ip,
        actor_user_agent=user_agent,
        changes=changes,
        metadata=metadata,
    )


async def audit_delete(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: UUID,
    resource_key: str,
    actor_principal_key: str,
    tenant_key: str = "default",
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a DELETE operation in the audit log."""
    ip, user_agent = extract_request_info(request)
    return await record_audit(
        db,
        action=AuditAction.DELETE,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_key=resource_key,
        actor_principal_key=actor_principal_key,
        tenant_key=tenant_key,
        actor_ip=ip,
        actor_user_agent=user_agent,
        metadata=metadata,
    )
