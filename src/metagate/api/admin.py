"""Admin API endpoints for CRUD operations on MetaGate entities."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID, uuid4
from typing import List

from ..database import get_db
from ..models.db_models import Principal, Profile, Manifest, Binding, SecretRef
from ..models.schemas import (
    PrincipalCreate, PrincipalResponse,
    ProfileCreate, ProfileResponse,
    ManifestCreate, ManifestResponse,
    BindingCreate, BindingResponse,
    SecretRefCreate, SecretRefResponse,
)
from ..services.bootstrap import FORBIDDEN_KEYS, check_forbidden_keys

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# Principals
@router.post("/principals", response_model=PrincipalResponse, status_code=201)
async def create_principal(
    data: PrincipalCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new principal."""
    principal = Principal(
        id=uuid4(),
        tenant_key=data.tenant_key,
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
):
    """List all principals for a tenant."""
    result = await db.execute(
        select(Principal).where(Principal.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/principals/{principal_id}", response_model=PrincipalResponse)
async def get_principal(
    principal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a principal by ID."""
    result = await db.execute(
        select(Principal).where(Principal.id == principal_id)
    )
    principal = result.scalar_one_or_none()
    if not principal:
        raise HTTPException(status_code=404, detail="Principal not found")
    return principal


@router.delete("/principals/{principal_id}", status_code=204)
async def delete_principal(
    principal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a principal."""
    result = await db.execute(
        select(Principal).where(Principal.id == principal_id)
    )
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
):
    """Create a new profile."""
    # Check for forbidden keys
    forbidden = check_forbidden_keys(data.capabilities) | check_forbidden_keys(data.policy)
    if forbidden:
        raise HTTPException(status_code=400, detail=f"Forbidden keys detected: {forbidden}")

    profile = Profile(
        id=uuid4(),
        tenant_key=data.tenant_key,
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
):
    """List all profiles for a tenant."""
    result = await db.execute(
        select(Profile).where(Profile.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a profile by ID."""
    result = await db.execute(
        select(Profile).where(Profile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a profile."""
    result = await db.execute(
        select(Profile).where(Profile.id == profile_id)
    )
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

    manifest = Manifest(
        id=uuid4(),
        tenant_key=data.tenant_key,
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
):
    """List all manifests for a tenant."""
    result = await db.execute(
        select(Manifest).where(Manifest.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/manifests/{manifest_id}", response_model=ManifestResponse)
async def get_manifest(
    manifest_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a manifest by ID."""
    result = await db.execute(
        select(Manifest).where(Manifest.id == manifest_id)
    )
    manifest = result.scalar_one_or_none()
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return manifest


@router.delete("/manifests/{manifest_id}", status_code=204)
async def delete_manifest(
    manifest_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a manifest."""
    result = await db.execute(
        select(Manifest).where(Manifest.id == manifest_id)
    )
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
):
    """Create a new binding."""
    # Verify principal exists
    result = await db.execute(
        select(Principal).where(Principal.id == data.principal_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Principal not found")

    # Verify profile exists
    result = await db.execute(
        select(Profile).where(Profile.id == data.profile_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Profile not found")

    # Verify manifest exists
    result = await db.execute(
        select(Manifest).where(Manifest.id == data.manifest_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Manifest not found")

    # Deactivate existing active bindings for this principal if creating active binding
    if data.active:
        result = await db.execute(
            select(Binding).where(
                Binding.principal_id == data.principal_id,
                Binding.active == True
            )
        )
        existing_bindings = result.scalars().all()
        for binding in existing_bindings:
            binding.active = False

    binding = Binding(
        id=uuid4(),
        tenant_key=data.tenant_key,
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
):
    """List all bindings for a tenant."""
    result = await db.execute(
        select(Binding).where(Binding.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.get("/bindings/{binding_id}", response_model=BindingResponse)
async def get_binding(
    binding_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a binding by ID."""
    result = await db.execute(
        select(Binding).where(Binding.id == binding_id)
    )
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    return binding


@router.delete("/bindings/{binding_id}", status_code=204)
async def delete_binding(
    binding_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a binding."""
    result = await db.execute(
        select(Binding).where(Binding.id == binding_id)
    )
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
):
    """Create a new secret reference."""
    if data.ref_kind not in ("env", "file"):
        raise HTTPException(status_code=400, detail="ref_kind must be 'env' or 'file'")

    secret_ref = SecretRef(
        id=uuid4(),
        tenant_key=data.tenant_key,
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
):
    """List all secret refs for a tenant."""
    result = await db.execute(
        select(SecretRef).where(SecretRef.tenant_key == tenant_key)
    )
    return result.scalars().all()


@router.delete("/secret-refs/{secret_ref_id}", status_code=204)
async def delete_secret_ref(
    secret_ref_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a secret reference."""
    result = await db.execute(
        select(SecretRef).where(SecretRef.id == secret_ref_id)
    )
    secret_ref = result.scalar_one_or_none()
    if not secret_ref:
        raise HTTPException(status_code=404, detail="Secret ref not found")
    await db.delete(secret_ref)
    await db.commit()
