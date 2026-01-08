"""Admin API endpoints for CRUD operations on MetaGate entities."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID, uuid4
from typing import List

from ..database import get_db
from ..config import get_settings
from ..models.db_models import Principal, Profile, Manifest, Binding, SecretRef
from ..models.schemas import (
    PrincipalCreate, PrincipalResponse,
    ProfileCreate, ProfileResponse,
    ManifestCreate, ManifestResponse,
    BindingCreate, BindingResponse,
    SecretRefCreate, SecretRefResponse,
)
from ..services.bootstrap import FORBIDDEN_KEYS, check_forbidden_keys
from ..auth.auth import AuthenticatedPrincipal, require_admin

router = APIRouter(prefix="/v1/admin", tags=["admin"])
settings = get_settings()


def resolve_tenant_key(auth: AuthenticatedPrincipal, requested: str | None) -> str:
    """Resolve tenant key for admin operations with optional cross-tenant access."""
    if settings.admin_allow_cross_tenant:
        return requested or auth.principal.tenant_key
    if requested and requested != auth.principal.tenant_key:
        raise HTTPException(status_code=403, detail="Cross-tenant admin access denied")
    return auth.principal.tenant_key


def apply_tenant_scope(query, auth: AuthenticatedPrincipal, model):
    """Apply tenant scoping to a query if cross-tenant access is disabled."""
    if settings.admin_allow_cross_tenant:
        return query
    return query.where(model.tenant_key == auth.principal.tenant_key)


# Principals
@router.post("/principals", response_model=PrincipalResponse, status_code=201)
async def create_principal(
    data: PrincipalCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Create a new principal."""
    tenant_key = resolve_tenant_key(auth, data.tenant_key)
    principal = Principal(
        id=uuid4(),
        tenant_key=tenant_key,
        principal_key=data.principal_key,
        auth_subject=data.auth_subject,
        principal_type=data.principal_type,
    )
    db.add(principal)
    try:
        await db.commit()
        await db.refresh(principal)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create principal: {e}")
    return principal


@router.get("/principals", response_model=List[PrincipalResponse])
async def list_principals(
    tenant_key: str = "default",
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """List all principals for a tenant."""
    tenant_key = resolve_tenant_key(auth, tenant_key)
    result = await db.execute(
        select(Principal).where(Principal.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/principals/{principal_id}", response_model=PrincipalResponse)
async def get_principal(
    principal_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Get a principal by ID."""
    query = select(Principal).where(Principal.id == principal_id)
    query = apply_tenant_scope(query, auth, Principal)
    result = await db.execute(query)
    principal = result.scalar_one_or_none()
    if not principal:
        raise HTTPException(status_code=404, detail="Principal not found")
    return principal


@router.delete("/principals/{principal_id}", status_code=204)
async def delete_principal(
    principal_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Delete a principal."""
    query = select(Principal).where(Principal.id == principal_id)
    query = apply_tenant_scope(query, auth, Principal)
    result = await db.execute(query)
    principal = result.scalar_one_or_none()
    if not principal:
        raise HTTPException(status_code=404, detail="Principal not found")
    await db.delete(principal)
    await db.commit()


# Profiles
@router.post("/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(
    data: ProfileCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Create a new profile."""
    # Check for forbidden keys
    forbidden = check_forbidden_keys(data.capabilities) | check_forbidden_keys(data.policy)
    if forbidden:
        raise HTTPException(status_code=400, detail=f"Forbidden keys detected: {forbidden}")

    tenant_key = resolve_tenant_key(auth, data.tenant_key)
    profile = Profile(
        id=uuid4(),
        tenant_key=tenant_key,
        profile_key=data.profile_key,
        capabilities=data.capabilities,
        policy=data.policy,
        startup_sla_seconds=data.startup_sla_seconds,
    )
    db.add(profile)
    try:
        await db.commit()
        await db.refresh(profile)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create profile: {e}")
    return profile


@router.get("/profiles", response_model=List[ProfileResponse])
async def list_profiles(
    tenant_key: str = "default",
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """List all profiles for a tenant."""
    tenant_key = resolve_tenant_key(auth, tenant_key)
    result = await db.execute(
        select(Profile).where(Profile.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Get a profile by ID."""
    query = select(Profile).where(Profile.id == profile_id)
    query = apply_tenant_scope(query, auth, Profile)
    result = await db.execute(query)
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Delete a profile."""
    query = select(Profile).where(Profile.id == profile_id)
    query = apply_tenant_scope(query, auth, Profile)
    result = await db.execute(query)
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.delete(profile)
    await db.commit()


# Manifests
@router.post("/manifests", response_model=ManifestResponse, status_code=201)
async def create_manifest(
    data: ManifestCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Create a new manifest."""
    # Check for forbidden keys
    manifest_data = {
        "environment": data.environment,
        "services": data.services,
        "memory_map": data.memory_map,
        "polling": data.polling,
        "schemas": data.schemas,
    }
    forbidden = check_forbidden_keys(manifest_data)
    if forbidden:
        raise HTTPException(status_code=400, detail=f"Forbidden keys detected: {forbidden}")

    tenant_key = resolve_tenant_key(auth, data.tenant_key)
    manifest = Manifest(
        id=uuid4(),
        tenant_key=tenant_key,
        manifest_key=data.manifest_key,
        deployment_key=data.deployment_key,
        environment=data.environment,
        services=data.services,
        memory_map=data.memory_map,
        polling=data.polling,
        schemas=data.schemas,
        version=data.version,
    )
    db.add(manifest)
    try:
        await db.commit()
        await db.refresh(manifest)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create manifest: {e}")
    return manifest


@router.get("/manifests", response_model=List[ManifestResponse])
async def list_manifests(
    tenant_key: str = "default",
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """List all manifests for a tenant."""
    tenant_key = resolve_tenant_key(auth, tenant_key)
    result = await db.execute(
        select(Manifest).where(Manifest.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/manifests/{manifest_id}", response_model=ManifestResponse)
async def get_manifest(
    manifest_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Get a manifest by ID."""
    query = select(Manifest).where(Manifest.id == manifest_id)
    query = apply_tenant_scope(query, auth, Manifest)
    result = await db.execute(query)
    manifest = result.scalar_one_or_none()
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return manifest


@router.delete("/manifests/{manifest_id}", status_code=204)
async def delete_manifest(
    manifest_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Delete a manifest."""
    query = select(Manifest).where(Manifest.id == manifest_id)
    query = apply_tenant_scope(query, auth, Manifest)
    result = await db.execute(query)
    manifest = result.scalar_one_or_none()
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    await db.delete(manifest)
    await db.commit()


# Bindings
@router.post("/bindings", response_model=BindingResponse, status_code=201)
async def create_binding(
    data: BindingCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Create a new binding."""
    tenant_key = resolve_tenant_key(auth, data.tenant_key)
    # Verify principal exists
    query = select(Principal).where(Principal.id == data.principal_id)
    query = apply_tenant_scope(query, auth, Principal)
    result = await db.execute(query)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Principal not found")

    # Verify profile exists
    query = select(Profile).where(Profile.id == data.profile_id)
    query = apply_tenant_scope(query, auth, Profile)
    result = await db.execute(query)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Profile not found")

    # Verify manifest exists
    query = select(Manifest).where(Manifest.id == data.manifest_id)
    query = apply_tenant_scope(query, auth, Manifest)
    result = await db.execute(query)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Manifest not found")

    # Deactivate existing active bindings for this principal if creating active binding
    if data.active:
        result = await db.execute(
            select(Binding).where(
                Binding.principal_id == data.principal_id,
                Binding.tenant_key == tenant_key,
                Binding.active == True
            )
        )
        existing_bindings = result.scalars().all()
        for binding in existing_bindings:
            binding.active = False

    binding = Binding(
        id=uuid4(),
        tenant_key=tenant_key,
        principal_id=data.principal_id,
        profile_id=data.profile_id,
        manifest_id=data.manifest_id,
        overrides=data.overrides,
        active=data.active,
    )
    db.add(binding)
    try:
        await db.commit()
        await db.refresh(binding)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create binding: {e}")
    return binding


@router.get("/bindings", response_model=List[BindingResponse])
async def list_bindings(
    tenant_key: str = "default",
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """List all bindings for a tenant."""
    tenant_key = resolve_tenant_key(auth, tenant_key)
    result = await db.execute(
        select(Binding).where(Binding.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/bindings/{binding_id}", response_model=BindingResponse)
async def get_binding(
    binding_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Get a binding by ID."""
    query = select(Binding).where(Binding.id == binding_id)
    query = apply_tenant_scope(query, auth, Binding)
    result = await db.execute(query)
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    return binding


@router.delete("/bindings/{binding_id}", status_code=204)
async def delete_binding(
    binding_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Delete a binding."""
    query = select(Binding).where(Binding.id == binding_id)
    query = apply_tenant_scope(query, auth, Binding)
    result = await db.execute(query)
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    await db.delete(binding)
    await db.commit()


# Secret Refs
@router.post("/secret-refs", response_model=SecretRefResponse, status_code=201)
async def create_secret_ref(
    data: SecretRefCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Create a new secret reference."""
    if data.ref_kind not in ("env", "file"):
        raise HTTPException(status_code=400, detail="ref_kind must be 'env' or 'file'")

    tenant_key = resolve_tenant_key(auth, data.tenant_key)
    secret_ref = SecretRef(
        id=uuid4(),
        tenant_key=tenant_key,
        secret_key=data.secret_key,
        ref_kind=data.ref_kind,
        ref_name=data.ref_name,
        ref_meta=data.ref_meta,
    )
    db.add(secret_ref)
    try:
        await db.commit()
        await db.refresh(secret_ref)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create secret ref: {e}")
    return secret_ref


@router.get("/secret-refs", response_model=List[SecretRefResponse])
async def list_secret_refs(
    tenant_key: str = "default",
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """List all secret refs for a tenant."""
    tenant_key = resolve_tenant_key(auth, tenant_key)
    result = await db.execute(
        select(SecretRef).where(SecretRef.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.delete("/secret-refs/{secret_ref_id}", status_code=204)
async def delete_secret_ref(
    secret_ref_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthenticatedPrincipal = Depends(require_admin),
):
    """Delete a secret reference."""
    query = select(SecretRef).where(SecretRef.id == secret_ref_id)
    query = apply_tenant_scope(query, auth, SecretRef)
    result = await db.execute(query)
    secret_ref = result.scalar_one_or_none()
    if not secret_ref:
        raise HTTPException(status_code=404, detail="Secret ref not found")
    await db.delete(secret_ref)
    await db.commit()
