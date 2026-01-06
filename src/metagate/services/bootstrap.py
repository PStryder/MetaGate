"""Bootstrap service - core logic for bootstrap and welcome packet generation."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib
import json
from typing import Optional, Any

from ..models.db_models import Principal, Binding, Profile, Manifest, StartupSession, SecretRef
from ..models.schemas import WelcomePacket, StartupBlock
from ..config import get_settings

settings = get_settings()

# Forbidden keys per spec section 9
FORBIDDEN_KEYS = {
    "tasks", "jobs", "work_items", "payloads",
    "deploy", "scale", "provision", "execute"
}


class BootstrapError(Exception):
    """Base error for bootstrap operations."""

    def __init__(self, message: str, status_code: int = 500, code: str = "BOOTSTRAP_ERROR"):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class ForbiddenKeyError(BootstrapError):
    """Raised when forbidden keys are detected."""

    def __init__(self, keys: set[str]):
        super().__init__(
            f"Forbidden keys detected: {keys}",
            status_code=400,
            code="FORBIDDEN_KEYS"
        )


def check_forbidden_keys(data: dict[str, Any], path: str = "") -> set[str]:
    """Recursively check for forbidden keys in a dict."""
    found = set()
    for key, value in data.items():
        if key.lower() in FORBIDDEN_KEYS:
            found.add(f"{path}.{key}" if path else key)
        if isinstance(value, dict):
            found.update(check_forbidden_keys(value, f"{path}.{key}" if path else key))
    return found


def generate_etag(data: dict[str, Any]) -> str:
    """Generate an ETag for the packet data."""
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(content.encode()).hexdigest()


def generate_redacted_hash(data: dict[str, Any]) -> str:
    """Generate a redacted hash for logging (no secrets)."""
    # Create a copy with sensitive fields redacted
    safe_data = {
        "principal_key": data.get("principal_key"),
        "component_key": data.get("component_key"),
        "profile": data.get("profile"),
        "manifest": data.get("manifest"),
        "issued_at": str(data.get("issued_at")),
    }
    content = json.dumps(safe_data, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def get_active_binding(
    db: AsyncSession,
    principal: Principal
) -> Optional[Binding]:
    """Get the active binding for a principal."""
    result = await db.execute(
        select(Binding)
        .where(
            Binding.principal_id == principal.id,
            Binding.active == True
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_required_env_refs(
    db: AsyncSession,
    tenant_key: str
) -> list[dict[str, Any]]:
    """Get required environment variable references."""
    result = await db.execute(
        select(SecretRef).where(
            SecretRef.tenant_key == tenant_key,
            SecretRef.status == "active"
        )
    )
    refs = result.scalars().all()

    return [
        {
            "secret_key": ref.secret_key,
            "ref_kind": ref.ref_kind,
            "ref_name": ref.ref_name,
            "ref_meta": ref.ref_meta
        }
        for ref in refs
    ]


async def create_startup_session(
    db: AsyncSession,
    principal: Principal,
    component_key: str,
    profile: Profile,
    manifest: Manifest,
    packet_etag: str,
    packet_hash_redacted: str,
) -> StartupSession:
    """Create a new startup session with OPEN status."""
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(seconds=profile.startup_sla_seconds)

    session = StartupSession(
        id=uuid4(),
        tenant_key=principal.tenant_key,
        deployment_key=manifest.deployment_key,
        subject_principal_key=principal.principal_key,
        component_key=component_key,
        profile_key=profile.profile_key,
        manifest_key=manifest.manifest_key,
        packet_etag=packet_etag,
        packet_hash_redacted=packet_hash_redacted,
        status="OPEN",
        opened_at=now,
        deadline_at=deadline,
        mirror_status="PENDING",
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    return session


async def perform_bootstrap(
    db: AsyncSession,
    principal: Principal,
    component_key: str,
    principal_key_hint: Optional[str],
    last_packet_etag: Optional[str],
) -> tuple[WelcomePacket, bool]:
    """
    Perform the bootstrap operation.

    Returns:
        Tuple of (WelcomePacket, is_cached) where is_cached indicates 304 response
    """
    # Verify principal_key hint if provided
    if principal_key_hint and principal_key_hint != principal.principal_key:
        raise BootstrapError(
            f"Principal key mismatch: hint={principal_key_hint}, actual={principal.principal_key}",
            status_code=409,
            code="PRINCIPAL_MISMATCH"
        )

    # Get active binding
    binding = await get_active_binding(db, principal)
    if not binding:
        raise BootstrapError(
            f"No active binding for principal {principal.principal_key}",
            status_code=403,
            code="NO_BINDING"
        )

    # Load profile and manifest
    result = await db.execute(select(Profile).where(Profile.id == binding.profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise BootstrapError("Profile not found", status_code=500, code="PROFILE_NOT_FOUND")

    result = await db.execute(select(Manifest).where(Manifest.id == binding.manifest_id))
    manifest = result.scalar_one_or_none()
    if not manifest:
        raise BootstrapError("Manifest not found", status_code=500, code="MANIFEST_NOT_FOUND")

    # Check for forbidden keys in manifest
    manifest_data = {
        "environment": manifest.environment,
        "services": manifest.services,
        "memory_map": manifest.memory_map,
        "polling": manifest.polling,
        "schemas": manifest.schemas,
    }
    forbidden = check_forbidden_keys(manifest_data)
    if forbidden:
        raise ForbiddenKeyError(forbidden)

    # Apply overrides
    capabilities = {**profile.capabilities}
    policy = {**profile.policy}
    services = {**manifest.services}
    memory_map = {**manifest.memory_map}
    polling = {**manifest.polling}
    schemas = {**manifest.schemas}

    if binding.overrides:
        if "capabilities" in binding.overrides:
            capabilities.update(binding.overrides["capabilities"])
        if "policy" in binding.overrides:
            policy.update(binding.overrides["policy"])
        if "services" in binding.overrides:
            services.update(binding.overrides["services"])
        if "memory_map" in binding.overrides:
            memory_map.update(binding.overrides["memory_map"])
        if "polling" in binding.overrides:
            polling.update(binding.overrides["polling"])
        if "schemas" in binding.overrides:
            schemas.update(binding.overrides["schemas"])

    # Get required env refs
    required_env = await get_required_env_refs(db, principal.tenant_key)

    # Build packet data for etag
    now = datetime.now(timezone.utc)
    packet_id = uuid4()

    packet_data = {
        "principal_key": principal.principal_key,
        "component_key": component_key,
        "profile": profile.profile_key,
        "manifest": manifest.manifest_key,
        "capabilities": capabilities,
        "policy": policy,
        "services": services,
        "memory_map": memory_map,
        "polling": polling,
        "schemas": schemas,
        "required_env": required_env,
        "manifest_version": manifest.version,
    }

    # Generate etag
    packet_etag = generate_etag(packet_data)

    # Check for 304 Not Modified
    if last_packet_etag and last_packet_etag == packet_etag:
        return None, True  # Signal 304

    # Create startup session
    packet_hash_redacted = generate_redacted_hash({**packet_data, "issued_at": now})
    startup_session = await create_startup_session(
        db, principal, component_key, profile, manifest,
        packet_etag, packet_hash_redacted
    )

    # Build startup block
    startup_block = StartupBlock(
        startup_id=startup_session.id,
        status="OPEN",
        deadline_at=startup_session.deadline_at,
    )

    # Build welcome packet
    welcome_packet = WelcomePacket(
        packet_id=packet_id,
        packet_etag=packet_etag,
        issued_at=now,
        principal_key=principal.principal_key,
        component_key=component_key,
        profile=profile.profile_key,
        manifest=manifest.manifest_key,
        capabilities=capabilities,
        policy=policy,
        services=services,
        memory_map=memory_map,
        polling=polling,
        schemas=schemas,
        required_env=required_env,
        startup=startup_block,
    )

    return welcome_packet, False
