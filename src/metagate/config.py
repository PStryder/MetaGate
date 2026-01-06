"""Configuration management for MetaGate."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://metagate:metagate@db:5432/metagate",
        alias="DATABASE_URL"
    )

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # Auth
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: Optional[str] = Field(default=None, alias="JWT_ISSUER")
    api_key_header: str = Field(default="X-API-Key", alias="API_KEY_HEADER")

    # MetaGate specific
    metagate_version: str = Field(default="0.1", alias="METAGATE_VERSION")
    default_startup_sla_seconds: int = Field(default=120, alias="DEFAULT_STARTUP_SLA_SECONDS")
    receipt_retention_hours: int = Field(default=72, alias="RECEIPT_RETENTION_HOURS")

    # Tenant defaults
    default_tenant_key: str = Field(default="default", alias="DEFAULT_TENANT_KEY")
    default_deployment_key: str = Field(default="default", alias="DEFAULT_DEPLOYMENT_KEY")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
