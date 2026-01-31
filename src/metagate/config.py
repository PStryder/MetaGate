"""Configuration management for MetaGate."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="METAGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://metagate:metagate@db:5432/metagate",
        description="Database connection URL"
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Enable debug mode")
    instance_id: str = Field(default="metagate-1", description="Instance identifier")

    # Auth
    jwt_secret: str = Field(default="change-me-in-production", description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_issuer: Optional[str] = Field(default=None, description="JWT issuer")
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    admin_principal_types: list[str] = Field(
        default=["admin"],
        description="Principal types allowed to access admin endpoints"
    )
    admin_principal_keys: list[str] = Field(
        default_factory=list,
        description="Explicit principal keys allowed to access admin endpoints"
    )
    admin_allow_cross_tenant: bool = Field(
        default=False,
        description="Allow admin operations across tenants"
    )

    # MetaGate specific
    metagate_version: str = Field(default="0.1", description="MetaGate version")
    default_startup_sla_seconds: int = Field(default=120, description="Default startup SLA in seconds")
    receipt_retention_hours: int = Field(default=72, description="Receipt retention in hours")

    # ReceiptGate integration
    receiptgate_endpoint: str = Field(default="", description="ReceiptGate MCP endpoint")
    receiptgate_auth_token: str = Field(default="", description="ReceiptGate auth token")
    receiptgate_emit_receipts: bool = Field(
        default=True,
        description="Emit startup receipts to ReceiptGate",
    )

    # Tenant defaults
    default_tenant_key: str = Field(default="default", description="Default tenant key")
    default_deployment_key: str = Field(default="default", description="Default deployment key")

    # CORS configuration (explicit allowlist for security)
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins (explicit allowlist for security)"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials in CORS requests"
    )
    cors_allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods"
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-Tenant-ID"],
        description="Allowed request headers"
    )

    # Rate limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests_per_minute: int = Field(default=100, description="Rate limit per minute")

    # Validators
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate PostgreSQL database URL format."""
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("database_url must be a PostgreSQL URL (postgresql:// or postgresql+asyncpg://)")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        """Validate JWT secret is not default in production."""
        debug = info.data.get("debug", False)
        if v == "change-me-in-production" and not debug:
            raise ValueError("jwt_secret must be changed from default value in production")
        return v

    @field_validator("receiptgate_endpoint")
    @classmethod
    def validate_receiptgate_endpoint(cls, v: str) -> str:
        """Validate ReceiptGate endpoint if provided."""
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("receiptgate_endpoint must start with http:// or https://")
        return v


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
