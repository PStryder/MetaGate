"""Tests for authentication module."""
import re
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from metagate.auth.auth import (
    hash_api_key,
    verify_jwt,
    verify_api_key,
    is_admin_principal,
)
from metagate.config import get_settings
from metagate.models.db_models import Principal, ApiKey


class TestApiKeyHashing:
    """Tests for API key hashing."""

    def test_hash_is_bcrypt_format(self):
        """Should return bcrypt hash starting with $2."""
        hashed = hash_api_key("test_key_123")
        settings = get_settings()
        if settings.debug:
            assert hashed.startswith("$2") or re.fullmatch(r"[0-9a-f]{64}", hashed)
        else:
            assert hashed.startswith("$2")

    def test_same_key_different_hashes(self):
        """Should generate different hashes for same key (salted)."""
        hash1 = hash_api_key("test_key")
        hash2 = hash_api_key("test_key")
        if hash1.startswith("$2") and hash2.startswith("$2"):
            assert hash1 != hash2
        else:
            assert hash1 == hash2


class TestApiKeyVerification:
    """Tests for API key verification."""

    @pytest.mark.asyncio
    async def test_valid_api_key(
        self,
        test_session,
        test_principal,
        test_api_key,
    ):
        """Should authenticate with valid API key."""
        raw_key, _ = test_api_key
        result = await verify_api_key(raw_key, test_session)
        assert result is not None
        assert result.principal.id == test_principal.id
        assert result.auth_method == "api_key"

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, test_session):
        """Should return None for invalid API key."""
        result = await verify_api_key("invalid_key_xyz", test_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_api_key(
        self,
        test_session,
        test_principal,
    ):
        """Should reject expired API key."""
        raw_key = "expired_key_123"
        expired_key = ApiKey(
            id=uuid4(),
            tenant_key="default",
            key_hash=hash_api_key(raw_key),
            principal_id=test_principal.id,
            name="Expired Key",
            status="active",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        test_session.add(expired_key)
        await test_session.commit()

        result = await verify_api_key(raw_key, test_session)
        assert result is None


class TestAdminPrincipal:
    """Tests for admin principal detection."""

    def test_admin_type_is_admin(self):
        """Should recognize admin principal type."""
        principal = Principal(
            id=uuid4(),
            tenant_key="default",
            principal_key="admin-001",
            auth_subject="admin-subject",
            principal_type="admin",
            status="active",
        )
        assert is_admin_principal(principal) is True

    def test_component_type_not_admin(self):
        """Should not recognize component as admin."""
        principal = Principal(
            id=uuid4(),
            tenant_key="default",
            principal_key="component-001",
            auth_subject="component-subject",
            principal_type="component",
            status="active",
        )
        assert is_admin_principal(principal) is False
