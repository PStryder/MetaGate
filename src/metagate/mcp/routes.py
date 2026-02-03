"""MetaGate MCP server (HTTP JSON-RPC)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from metagate.auth.auth import (
    AuthenticatedPrincipal,
    is_admin_principal,
    verify_api_key,
    verify_jwt,
)
from metagate.config import get_settings
from metagate.database import AsyncSessionLocal
from metagate.middleware import get_rate_limiter
from metagate.models.db_models import Principal, Profile, Manifest, Binding, SecretRef
from metagate.models.schemas import (
    BootstrapRequest,
    DiscoveryResponse,
    PrincipalCreate,
    PrincipalResponse,
    ProfileCreate,
    ProfileResponse,
    ManifestCreate,
    ManifestResponse,
    BindingCreate,
    BindingResponse,
    SecretRefCreate,
    SecretRefResponse,
)
from metagate.services.bootstrap import BootstrapError, ForbiddenKeyError, perform_bootstrap
from metagate.services.startup import StartupError, mark_startup_failed, mark_startup_ready
from metagate.tenancy import apply_tenant_scope, resolve_tenant_key


class MCPRequest(BaseModel):
    """JSON-RPC request envelope for MCP."""

    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: Any = None


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


MCP_TOOLS = [
    {
        "name": "metagate.discovery",
        "description": "Service discovery",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.health",
        "description": "Health check / service info",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.bootstrap",
        "description": "Bootstrap a component, returns Welcome Packet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "component_key": {"type": "string"},
                "principal_key": {"type": "string"},
                "last_packet_etag": {"type": "string"},
                "auth_token": {"type": "string"},
            },
            "required": ["component_key"],
        },
    },
    {
        "name": "metagate.startup_ready",
        "description": "Component reports successful initialization",
        "inputSchema": {
            "type": "object",
            "properties": {
                "startup_id": {"type": "string"},
                "build_version": {"type": "string"},
                "health": {"type": "string"},
                "auth_token": {"type": "string"},
            },
            "required": ["startup_id", "build_version"],
        },
    },
    {
        "name": "metagate.startup_failed",
        "description": "Component reports startup failure",
        "inputSchema": {
            "type": "object",
            "properties": {
                "startup_id": {"type": "string"},
                "error": {"type": "string"},
                "details": {"type": "object"},
                "auth_token": {"type": "string"},
            },
            "required": ["startup_id", "error"],
        },
    },
    {
        "name": "metagate.admin_principals",
        "description": "Manage principals",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.admin_profiles",
        "description": "Manage profiles",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.admin_manifests",
        "description": "Manage manifests",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.admin_bindings",
        "description": "Manage bindings",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "metagate.admin_secret_refs",
        "description": "Manage secret references",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


router = APIRouter(prefix="/mcp", tags=["mcp"])


def _extract_auth_token(arguments: dict[str, Any], request: Request) -> Optional[str]:
    token = arguments.pop("auth_token", None)
    if token:
        return token
    auth_header = request.headers.get("authorization")
    api_key_header = request.headers.get("x-api-key")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1]
    if api_key_header:
        return api_key_header
    return None


async def _rate_limit(request: Request) -> None:
    settings = get_settings()
    limiter = get_rate_limiter(
        calls_per_minute=settings.rate_limit_requests_per_minute,
        enabled=settings.rate_limit_enabled,
    )
    await limiter.check_request(request)


async def _authenticate(
    db,
    token: Optional[str],
) -> AuthenticatedPrincipal:
    if not token:
        raise ValueError("Missing auth token")
    auth = await verify_jwt(token, db)
    if not auth:
        auth = await verify_api_key(token, db)
    if not auth or not auth.principal:
        raise ValueError("Invalid authentication credentials")
    return auth


async def _handle_admin_principals(db, auth: AuthenticatedPrincipal, arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action", "list")
    if action == "create":
        data = arguments.get("data") or arguments
        create = PrincipalCreate(**data)
        tenant_key = resolve_tenant_key(auth, create.tenant_key)
        principal = Principal(
            tenant_key=tenant_key,
            principal_key=create.principal_key,
            auth_subject=create.auth_subject,
            principal_type=create.principal_type,
        )
        db.add(principal)
        await db.commit()
        await db.refresh(principal)
        return PrincipalResponse.model_validate(principal).model_dump()

    if action == "list":
        tenant_key = resolve_tenant_key(auth, arguments.get("tenant_key"))
        result = await db.execute(select(Principal).where(Principal.tenant_key == tenant_key))
        return {"principals": [PrincipalResponse.model_validate(p).model_dump() for p in result.scalars().all()]}

    if action == "get":
        principal_id = arguments.get("principal_id")
        if not principal_id:
            raise ValueError("principal_id is required")
        query = select(Principal).where(Principal.id == UUID(principal_id))
        query = apply_tenant_scope(query, auth, Principal)
        result = await db.execute(query)
        principal = result.scalar_one_or_none()
        if not principal:
            raise ValueError("Principal not found")
        return PrincipalResponse.model_validate(principal).model_dump()

    if action == "delete":
        principal_id = arguments.get("principal_id")
        if not principal_id:
            raise ValueError("principal_id is required")
        query = select(Principal).where(Principal.id == UUID(principal_id))
        query = apply_tenant_scope(query, auth, Principal)
        result = await db.execute(query)
        principal = result.scalar_one_or_none()
        if not principal:
            raise ValueError("Principal not found")
        await db.delete(principal)
        await db.commit()
        return {"deleted": True}

    raise ValueError(f"Unsupported action: {action}")


async def _handle_admin_profiles(db, auth: AuthenticatedPrincipal, arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action", "list")
    if action == "create":
        data = arguments.get("data") or arguments
        create = ProfileCreate(**data)
        tenant_key = resolve_tenant_key(auth, create.tenant_key)
        profile = Profile(
            tenant_key=tenant_key,
            profile_key=create.profile_key,
            capabilities=create.capabilities,
            policy=create.policy,
            startup_sla_seconds=create.startup_sla_seconds,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return ProfileResponse.model_validate(profile).model_dump()

    if action == "list":
        tenant_key = resolve_tenant_key(auth, arguments.get("tenant_key"))
        result = await db.execute(select(Profile).where(Profile.tenant_key == tenant_key))
        return {"profiles": [ProfileResponse.model_validate(p).model_dump() for p in result.scalars().all()]}

    if action == "get":
        profile_id = arguments.get("profile_id")
        profile_key = arguments.get("profile_key")
        if profile_id:
            query = select(Profile).where(Profile.id == UUID(profile_id))
        elif profile_key:
            query = select(Profile).where(Profile.profile_key == profile_key)
        else:
            raise ValueError("profile_id or profile_key is required")
        query = apply_tenant_scope(query, auth, Profile)
        result = await db.execute(query)
        profile = result.scalar_one_or_none()
        if not profile:
            raise ValueError("Profile not found")
        return ProfileResponse.model_validate(profile).model_dump()

    if action == "delete":
        profile_id = arguments.get("profile_id")
        if not profile_id:
            raise ValueError("profile_id is required")
        query = select(Profile).where(Profile.id == UUID(profile_id))
        query = apply_tenant_scope(query, auth, Profile)
        result = await db.execute(query)
        profile = result.scalar_one_or_none()
        if not profile:
            raise ValueError("Profile not found")
        await db.delete(profile)
        await db.commit()
        return {"deleted": True}

    raise ValueError(f"Unsupported action: {action}")


async def _handle_admin_manifests(db, auth: AuthenticatedPrincipal, arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action", "list")
    if action == "create":
        data = arguments.get("data") or arguments
        create = ManifestCreate(**data)
        tenant_key = resolve_tenant_key(auth, create.tenant_key)
        manifest = Manifest(
            tenant_key=tenant_key,
            manifest_key=create.manifest_key,
            deployment_key=create.deployment_key,
            environment=create.environment,
            services=create.services,
            memory_map=create.memory_map,
            polling=create.polling,
            schemas=create.schemas,
            version=create.version,
        )
        db.add(manifest)
        await db.commit()
        await db.refresh(manifest)
        return ManifestResponse.model_validate(manifest).model_dump()

    if action == "list":
        tenant_key = resolve_tenant_key(auth, arguments.get("tenant_key"))
        result = await db.execute(select(Manifest).where(Manifest.tenant_key == tenant_key))
        return {"manifests": [ManifestResponse.model_validate(m).model_dump() for m in result.scalars().all()]}

    if action == "get":
        manifest_id = arguments.get("manifest_id")
        manifest_key = arguments.get("manifest_key")
        if manifest_id:
            query = select(Manifest).where(Manifest.id == UUID(manifest_id))
        elif manifest_key:
            query = select(Manifest).where(Manifest.manifest_key == manifest_key)
        else:
            raise ValueError("manifest_id or manifest_key is required")
        query = apply_tenant_scope(query, auth, Manifest)
        result = await db.execute(query)
        manifest = result.scalar_one_or_none()
        if not manifest:
            raise ValueError("Manifest not found")
        return ManifestResponse.model_validate(manifest).model_dump()

    if action == "delete":
        manifest_id = arguments.get("manifest_id")
        if not manifest_id:
            raise ValueError("manifest_id is required")
        query = select(Manifest).where(Manifest.id == UUID(manifest_id))
        query = apply_tenant_scope(query, auth, Manifest)
        result = await db.execute(query)
        manifest = result.scalar_one_or_none()
        if not manifest:
            raise ValueError("Manifest not found")
        await db.delete(manifest)
        await db.commit()
        return {"deleted": True}

    raise ValueError(f"Unsupported action: {action}")


async def _handle_admin_bindings(db, auth: AuthenticatedPrincipal, arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action", "list")
    if action == "create":
        data = arguments.get("data") or arguments
        create = BindingCreate(**data)
        tenant_key = resolve_tenant_key(auth, create.tenant_key)
        binding = Binding(
            tenant_key=tenant_key,
            principal_id=create.principal_id,
            profile_id=create.profile_id,
            manifest_id=create.manifest_id,
            overrides=create.overrides,
            active=create.active,
        )
        db.add(binding)
        await db.commit()
        await db.refresh(binding)
        return BindingResponse.model_validate(binding).model_dump()

    if action == "list":
        tenant_key = resolve_tenant_key(auth, arguments.get("tenant_key"))
        result = await db.execute(select(Binding).where(Binding.tenant_key == tenant_key))
        return {"bindings": [BindingResponse.model_validate(b).model_dump() for b in result.scalars().all()]}

    if action == "get":
        binding_id = arguments.get("binding_id")
        if not binding_id:
            raise ValueError("binding_id is required")
        query = select(Binding).where(Binding.id == UUID(binding_id))
        query = apply_tenant_scope(query, auth, Binding)
        result = await db.execute(query)
        binding = result.scalar_one_or_none()
        if not binding:
            raise ValueError("Binding not found")
        return BindingResponse.model_validate(binding).model_dump()

    if action == "delete":
        binding_id = arguments.get("binding_id")
        if not binding_id:
            raise ValueError("binding_id is required")
        query = select(Binding).where(Binding.id == UUID(binding_id))
        query = apply_tenant_scope(query, auth, Binding)
        result = await db.execute(query)
        binding = result.scalar_one_or_none()
        if not binding:
            raise ValueError("Binding not found")
        await db.delete(binding)
        await db.commit()
        return {"deleted": True}

    raise ValueError(f"Unsupported action: {action}")


async def _handle_admin_secret_refs(db, auth: AuthenticatedPrincipal, arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action", "list")
    if action == "create":
        data = arguments.get("data") or arguments
        create = SecretRefCreate(**data)
        tenant_key = resolve_tenant_key(auth, create.tenant_key)
        secret_ref = SecretRef(
            tenant_key=tenant_key,
            secret_key=create.secret_key,
            ref_kind=create.ref_kind,
            ref_name=create.ref_name,
            ref_meta=create.ref_meta,
        )
        db.add(secret_ref)
        await db.commit()
        await db.refresh(secret_ref)
        return SecretRefResponse.model_validate(secret_ref).model_dump()

    if action == "list":
        tenant_key = resolve_tenant_key(auth, arguments.get("tenant_key"))
        result = await db.execute(select(SecretRef).where(SecretRef.tenant_key == tenant_key))
        return {"secret_refs": [SecretRefResponse.model_validate(s).model_dump() for s in result.scalars().all()]}

    if action == "delete":
        secret_ref_id = arguments.get("secret_ref_id")
        if not secret_ref_id:
            raise ValueError("secret_ref_id is required")
        query = select(SecretRef).where(SecretRef.id == UUID(secret_ref_id))
        query = apply_tenant_scope(query, auth, SecretRef)
        result = await db.execute(query)
        secret_ref = result.scalar_one_or_none()
        if not secret_ref:
            raise ValueError("Secret ref not found")
        await db.delete(secret_ref)
        await db.commit()
        return {"deleted": True}

    raise ValueError(f"Unsupported action: {action}")


async def _handle_tool(name: str, arguments: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = get_settings()
    if name == "metagate.discovery":
        response = DiscoveryResponse(
            metagate_version=settings.metagate_version,
            bootstrap_endpoint="/mcp",
            supported_auth=["jwt", "api_key"],
        )
        return response.model_dump()

    if name == "metagate.health":
        return {
            "status": "healthy",
            "service": "MetaGate",
            "version": settings.metagate_version,
            "instance_id": settings.instance_id,
        }

    auth_token = _extract_auth_token(arguments, request)
    async with AsyncSessionLocal() as db:
        auth = await _authenticate(db, auth_token)

        if name == "metagate.bootstrap":
            request_model = BootstrapRequest(**arguments)
            try:
                packet, is_cached = await perform_bootstrap(
                    db=db,
                    principal=auth.principal,
                    component_key=request_model.component_key,
                    principal_key_hint=request_model.principal_key,
                    last_packet_etag=request_model.last_packet_etag,
                )
            except ForbiddenKeyError as exc:
                raise ValueError(exc.message)
            except BootstrapError as exc:
                raise ValueError(exc.message)

            if is_cached:
                return {"not_modified": True}
            return {"packet": packet.model_dump(), "packet_etag": packet.packet_etag}

        if name == "metagate.startup_ready":
            try:
                response = await mark_startup_ready(
                    db=db,
                    startup_id=UUID(arguments["startup_id"]),
                    build_version=arguments["build_version"],
                    health=arguments.get("health"),
                )
                return response.model_dump()
            except StartupError as exc:
                raise ValueError(exc.message)

        if name == "metagate.startup_failed":
            try:
                response = await mark_startup_failed(
                    db=db,
                    startup_id=UUID(arguments["startup_id"]),
                    error=arguments["error"],
                    details=arguments.get("details"),
                )
                return response.model_dump()
            except StartupError as exc:
                raise ValueError(exc.message)

        if name.startswith("metagate.admin_"):
            if not auth.principal or not is_admin_principal(auth.principal):
                raise ValueError("Admin privileges required")

            if name == "metagate.admin_principals":
                return await _handle_admin_principals(db, auth, arguments)
            if name == "metagate.admin_profiles":
                return await _handle_admin_profiles(db, auth, arguments)
            if name == "metagate.admin_manifests":
                return await _handle_admin_manifests(db, auth, arguments)
            if name == "metagate.admin_bindings":
                return await _handle_admin_bindings(db, auth, arguments)
            if name == "metagate.admin_secret_refs":
                return await _handle_admin_secret_refs(db, auth, arguments)

    raise ValueError(f"Unknown tool: {name}")


@router.post("")
async def mcp_entry(request_body: MCPRequest, request: Request):
    await _rate_limit(request)

    if request_body.method == "tools/list":
        return _jsonrpc_result(request_body.id, {"tools": MCP_TOOLS})

    if request_body.method != "tools/call":
        return _jsonrpc_error(request_body.id, -32601, f"Method not found: {request_body.method}")

    params = request_body.params or {}
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(request_body.id, -32602, "Missing tool name")

    try:
        result = await _handle_tool(tool_name, arguments, request)
        return _jsonrpc_result(request_body.id, result)
    except Exception as exc:
        return _jsonrpc_error(request_body.id, getattr(exc, "code", "ERROR"), str(exc))
