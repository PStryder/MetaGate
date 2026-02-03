"""Pydantic schemas for API request/response models."""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


# =============================================================================
# Health & Service Models
# =============================================================================

class HealthResponse(BaseModel):
    """Standard health check response"""
    status: str
    service: str = "MetaGate"
    version: str
    instance_id: str


# =============================================================================
# Request & Response Schemas
# =============================================================================

# Request schemas
class BootstrapRequest(BaseModel):
    """Request body for metagate.bootstrap MCP tool."""
    component_key: str = Field(..., description="The component being instantiated")
    principal_key: Optional[str] = Field(None, description="Optional principal hint")
    last_packet_etag: Optional[str] = Field(None, description="ETag for caching")


class StartupReadyRequest(BaseModel):
    """Request body for metagate.startup_ready MCP tool."""
    startup_id: UUID = Field(..., description="Startup session ID")
    build_version: str = Field(..., description="Build version of the component")
    health: Optional[str] = Field(None, description="Optional health summary")


class StartupFailedRequest(BaseModel):
    """Request body for metagate.startup_failed MCP tool."""
    startup_id: UUID = Field(..., description="Startup session ID")
    error: str = Field(..., description="Error message")
    details: Optional[dict[str, Any]] = Field(default_factory=dict)


# Response schemas
class DiscoveryResponse(BaseModel):
    """Response for metagate.discovery MCP tool."""
    metagate_version: str
    bootstrap_endpoint: str
    supported_auth: list[str]


class StartupBlock(BaseModel):
    """Startup information block in Welcome Packet."""
    startup_id: UUID
    status: str = "OPEN"
    deadline_at: datetime
    followup: list[str] = [
        "metagate.startup_ready",
        "metagate.startup_failed",
    ]


class WelcomePacket(BaseModel):
    """Welcome Packet returned on successful bootstrap."""
    packet_id: UUID
    packet_etag: str
    issued_at: datetime
    principal_key: str
    component_key: str
    profile: str
    manifest: str
    capabilities: dict[str, Any]
    policy: dict[str, Any]
    services: dict[str, Any]
    memory_map: dict[str, Any]
    polling: dict[str, Any]
    schemas: dict[str, Any]
    required_env: list[dict[str, Any]]
    startup: StartupBlock


class StartupAckResponse(BaseModel):
    """Response for startup ready/failed endpoints."""
    startup_id: UUID
    status: str
    acknowledged_at: datetime


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


# Admin schemas for CRUD operations
class PrincipalCreate(BaseModel):
    """Create a new principal."""
    principal_key: str
    auth_subject: str
    principal_type: str
    tenant_key: Optional[str] = "default"


class PrincipalResponse(BaseModel):
    """Principal response."""
    id: UUID
    tenant_key: str
    principal_key: str
    auth_subject: str
    principal_type: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileCreate(BaseModel):
    """Create a new profile."""
    profile_key: str
    capabilities: dict[str, Any]
    policy: dict[str, Any]
    startup_sla_seconds: int = 120
    tenant_key: Optional[str] = "default"


class ProfileResponse(BaseModel):
    """Profile response."""
    id: UUID
    tenant_key: str
    profile_key: str
    capabilities: dict[str, Any]
    policy: dict[str, Any]
    startup_sla_seconds: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ManifestCreate(BaseModel):
    """Create a new manifest."""
    manifest_key: str
    deployment_key: str = "default"
    environment: dict[str, Any]
    services: dict[str, Any]
    memory_map: dict[str, Any]
    polling: dict[str, Any]
    schemas: dict[str, Any]
    version: int = 1
    tenant_key: Optional[str] = "default"


class ManifestResponse(BaseModel):
    """Manifest response."""
    id: UUID
    tenant_key: str
    manifest_key: str
    deployment_key: str
    environment: dict[str, Any]
    services: dict[str, Any]
    memory_map: dict[str, Any]
    polling: dict[str, Any]
    schemas: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BindingCreate(BaseModel):
    """Create a new binding."""
    principal_id: UUID
    profile_id: UUID
    manifest_id: UUID
    overrides: Optional[dict[str, Any]] = None
    active: bool = True
    tenant_key: Optional[str] = "default"


class BindingResponse(BaseModel):
    """Binding response."""
    id: UUID
    tenant_key: str
    principal_id: UUID
    profile_id: UUID
    manifest_id: UUID
    overrides: Optional[dict[str, Any]]
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SecretRefCreate(BaseModel):
    """Create a new secret reference."""
    secret_key: str
    ref_kind: str = "env"
    ref_name: str
    ref_meta: Optional[dict[str, Any]] = None
    tenant_key: Optional[str] = "default"


class SecretRefResponse(BaseModel):
    """Secret reference response."""
    id: UUID
    tenant_key: str
    secret_key: str
    ref_kind: str
    ref_name: str
    ref_meta: Optional[dict[str, Any]]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
