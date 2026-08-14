"""Issue, list and revoke API keys for principals.

MetaGate could authenticate principals but had no way to *create* credentials
for them, so every component identity had to be inserted into the database out
of band -- the demo stack seeded keys with raw SQL, and a principal created by
metagate.instantiate_problemata could never authenticate at all because nothing
could mint it a key.

Handling rules, which are the reason this is a service rather than three lines
in the route handler:

- The plaintext key is generated here, returned exactly once, and never stored.
  Only its hash is persisted, so a lost key is reissued rather than recovered.
- Keys are hashed with the same helper the verifier uses, so issuance and
  verification cannot drift apart.
- Revocation marks status rather than deleting, so an audit trail of what was
  issued and withdrawn survives.
- Listing never returns key material, not even truncated.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.auth import hash_api_key
from ..models.db_models import ApiKey, Principal

KEY_PREFIX = "mgk_"
KEY_ENTROPY_BYTES = 32


class ApiKeyError(Exception):
    """Raised when a key operation cannot be completed."""

    def __init__(self, message: str, code: str = "API_KEY_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def generate_api_key() -> str:
    """Generate a new opaque API key."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(KEY_ENTROPY_BYTES)}"


def _serialize(record: ApiKey, principal_key: Optional[str] = None) -> dict[str, Any]:
    """Describe a key without ever exposing key material."""
    return {
        "api_key_id": str(record.id),
        "tenant_key": record.tenant_key,
        "principal_id": str(record.principal_id) if record.principal_id else None,
        "principal_key": principal_key,
        "name": record.name,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "created_by": record.created_by,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
    }


async def _resolve_principal(
    db: AsyncSession,
    *,
    tenant_key: str,
    principal_key: Optional[str],
    principal_id: Optional[str],
) -> Principal:
    if principal_key:
        stmt = select(Principal).where(Principal.principal_key == principal_key)
    elif principal_id:
        try:
            stmt = select(Principal).where(Principal.id == UUID(principal_id))
        except ValueError as exc:
            raise ApiKeyError(f"principal_id is not a UUID: {principal_id}", "INVALID_PRINCIPAL") from exc
    else:
        raise ApiKeyError("principal_key or principal_id is required", "INVALID_PRINCIPAL")

    principal = (await db.execute(stmt)).scalar_one_or_none()
    if principal is None:
        raise ApiKeyError("Principal not found", "PRINCIPAL_NOT_FOUND")
    if principal.tenant_key != tenant_key:
        # Refuse across tenants rather than silently issuing into another one.
        raise ApiKeyError("Principal belongs to a different tenant", "TENANT_MISMATCH")
    return principal


async def issue_api_key(
    db: AsyncSession,
    *,
    tenant_key: str,
    principal_key: Optional[str] = None,
    principal_id: Optional[str] = None,
    name: Optional[str] = None,
    expires_in_days: Optional[int] = None,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    """Mint a key for a principal and return it once, in plaintext."""
    principal = await _resolve_principal(
        db, tenant_key=tenant_key, principal_key=principal_key, principal_id=principal_id
    )

    if expires_in_days is not None and expires_in_days <= 0:
        raise ApiKeyError("expires_in_days must be positive", "INVALID_EXPIRY")

    api_key = generate_api_key()
    record = ApiKey(
        id=uuid4(),
        tenant_key=tenant_key,
        key_hash=hash_api_key(api_key),
        principal_id=principal.id,
        name=name or f"Key for {principal.principal_key}",
        status="active",
        created_by=created_by,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        ),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    result = _serialize(record, principal.principal_key)
    # The only time this value exists outside the caller's process.
    result["api_key"] = api_key
    result["warning"] = "Store this key now; it cannot be retrieved again."
    return result


async def list_api_keys(
    db: AsyncSession,
    *,
    tenant_key: str,
    principal_key: Optional[str] = None,
    include_revoked: bool = False,
) -> dict[str, Any]:
    """List key metadata for a tenant. Never returns key material."""
    stmt = select(ApiKey, Principal).join(
        Principal, ApiKey.principal_id == Principal.id, isouter=True
    ).where(ApiKey.tenant_key == tenant_key)
    if not include_revoked:
        stmt = stmt.where(ApiKey.status == "active")

    rows = (await db.execute(stmt)).all()
    keys = [
        _serialize(record, principal.principal_key if principal else None)
        for record, principal in rows
        if principal_key is None or (principal is not None and principal.principal_key == principal_key)
    ]
    return {"api_keys": keys, "count": len(keys)}


async def revoke_api_key(
    db: AsyncSession,
    *,
    tenant_key: str,
    api_key_id: str,
) -> dict[str, Any]:
    """Revoke a key by id. Idempotent: revoking twice is not an error."""
    try:
        key_uuid = UUID(api_key_id)
    except ValueError as exc:
        raise ApiKeyError(f"api_key_id is not a UUID: {api_key_id}", "INVALID_KEY_ID") from exc

    record = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_uuid))
    ).scalar_one_or_none()
    if record is None:
        raise ApiKeyError("API key not found", "KEY_NOT_FOUND")
    if record.tenant_key != tenant_key:
        raise ApiKeyError("API key belongs to a different tenant", "TENANT_MISMATCH")

    already = record.status == "revoked"
    record.status = "revoked"
    await db.commit()
    await db.refresh(record)

    result = _serialize(record)
    result["already_revoked"] = already
    return result
