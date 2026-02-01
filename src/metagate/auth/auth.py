"""Authentication module supporting JWT and API Key."""
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Optional
import hashlib
import secrets

from passlib.hash import bcrypt

from ..config import get_settings
from ..database import get_db
from ..models.db_models import Principal, ApiKey

settings = get_settings()

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)


class AuthenticatedPrincipal:
    """Represents an authenticated principal."""

    def __init__(
        self,
        auth_subject: str,
        principal: Optional[Principal] = None,
        auth_method: str = "unknown"
    ):
        self.auth_subject = auth_subject
        self.principal = principal
        self.auth_method = auth_method

    @property
    def principal_key(self) -> Optional[str]:
        return self.principal.principal_key if self.principal else None


def is_admin_principal(principal: Principal) -> bool:
    """Return True if principal is allowed to access admin endpoints."""
    if principal.principal_type in settings.admin_principal_types:
        return True
    if principal.principal_key in settings.admin_principal_keys:
        return True
    return False


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage/lookup."""
    try:
        return bcrypt.hash(api_key)
    except Exception:
        if settings.debug:
            return hashlib.sha256(api_key.encode()).hexdigest()
        raise


def _is_bcrypt_hash(value: str) -> bool:
    return value.startswith("$2")


async def verify_jwt(token: str, db: AsyncSession) -> Optional[AuthenticatedPrincipal]:
    """Verify a JWT token and return the authenticated principal."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False}  # Audience verification optional
        )

        # Check issuer if configured
        if settings.jwt_issuer and payload.get("iss") != settings.jwt_issuer:
            return None

        # Extract subject
        auth_subject = payload.get("sub")
        if not auth_subject:
            return None

        # Look up principal by auth_subject
        result = await db.execute(
            select(Principal).where(
                Principal.auth_subject == auth_subject,
                Principal.status == "active"
            )
        )
        principal = result.scalar_one_or_none()

        return AuthenticatedPrincipal(
            auth_subject=auth_subject,
            principal=principal,
            auth_method="jwt"
        )

    except JWTError:
        return None


async def verify_api_key(api_key: str, db: AsyncSession) -> Optional[AuthenticatedPrincipal]:
    """Verify an API key and return the authenticated principal."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.status == "active")
    )
    api_key_records = result.scalars().all()

    now = datetime.now(timezone.utc)
    legacy_hash = hashlib.sha256(api_key.encode()).hexdigest()
    api_key_record = None
    upgrade_legacy = False

    for record in api_key_records:
        if record.expires_at and record.expires_at < now:
            continue
        if _is_bcrypt_hash(record.key_hash):
            if bcrypt.verify(api_key, record.key_hash):
                api_key_record = record
                break
        else:
            if secrets.compare_digest(record.key_hash, legacy_hash):
                api_key_record = record
                upgrade_legacy = True
                break

    if not api_key_record:
        return None

    # Check expiration
    if api_key_record.expires_at and api_key_record.expires_at < now:
        return None

    if upgrade_legacy:
        api_key_record.key_hash = hash_api_key(api_key)

    # Update last used timestamp (best effort, non-blocking)
    api_key_record.last_used_at = now
    await db.commit()

    # Get principal
    result = await db.execute(
        select(Principal).where(
            Principal.id == api_key_record.principal_id,
            Principal.status == "active"
        )
    )
    principal = result.scalar_one_or_none()

    if not principal:
        return None

    return AuthenticatedPrincipal(
        auth_subject=principal.auth_subject,
        principal=principal,
        auth_method="api_key"
    )


async def get_authenticated_principal(
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedPrincipal:
    """
    Dependency that authenticates the caller via JWT or API key.
    Returns the authenticated principal or raises 401/403.
    """
    authenticated = None

    # Try JWT first
    if bearer and bearer.credentials:
        authenticated = await verify_jwt(bearer.credentials, db)

    # Fall back to API key
    if not authenticated and api_key:
        authenticated = await verify_api_key(api_key, db)

    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authenticated.principal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal not found or inactive",
        )

    return authenticated


async def require_admin(
    auth: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> AuthenticatedPrincipal:
    """Require admin privileges for sensitive endpoints."""
    if not auth.principal or not is_admin_principal(auth.principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return auth
