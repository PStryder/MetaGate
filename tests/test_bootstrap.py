"""Tests for bootstrap service and API."""
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from metagate.services.bootstrap import (
    perform_bootstrap,
    check_forbidden_keys,
    BootstrapError,
    ForbiddenKeyError,
    cleanup_old_sessions,
)
from metagate.models.db_models import Principal, Profile, Manifest, Binding, StartupSession


class TestForbiddenKeys:
    """Tests for forbidden key detection."""

    def test_detects_forbidden_keys_at_root(self):
        """Should detect forbidden keys at root level."""
        data = {"tasks": [], "services": {}}
        found = check_forbidden_keys(data)
        assert "tasks" in found

    def test_detects_forbidden_keys_nested(self):
        """Should detect forbidden keys in nested dicts."""
        data = {"config": {"deploy": True, "name": "test"}}
        found = check_forbidden_keys(data)
        assert "config.deploy" in found

    def test_detects_multiple_forbidden_keys(self):
        """Should detect multiple forbidden keys."""
        data = {
            "jobs": [],
            "inner": {"payloads": {}, "valid": True},
            "execute": "something",
        }
        found = check_forbidden_keys(data)
        assert len(found) == 3
        assert "jobs" in found
        assert "inner.payloads" in found
        assert "execute" in found

    def test_case_insensitive_detection(self):
        """Should detect forbidden keys case-insensitively."""
        data = {"TASKS": [], "Deploy": True}
        found = check_forbidden_keys(data)
        assert len(found) == 2

    def test_no_forbidden_keys(self):
        """Should return empty set when no forbidden keys."""
        data = {"services": {}, "config": {"name": "test"}}
        found = check_forbidden_keys(data)
        assert len(found) == 0


class TestComponentKeyValidation:
    """Tests for component_key validation against allowed_components."""

    @pytest.mark.asyncio
    async def test_allowed_component_succeeds(
        self,
        test_session,
        test_principal,
        test_profile,
        test_manifest,
        test_binding,
    ):
        """Should succeed when component_key is in allowed_components."""
        packet, cached = await perform_bootstrap(
            test_session,
            test_principal,
            "allowed-component",
            None,
            None,
        )
        assert packet is not None
        assert packet.component_key == "allowed-component"
        assert not cached

    @pytest.mark.asyncio
    async def test_disallowed_component_fails(
        self,
        test_session,
        test_principal,
        test_profile,
        test_manifest,
        test_binding,
    ):
        """Should fail when component_key is not in allowed_components."""
        with pytest.raises(BootstrapError) as exc_info:
            await perform_bootstrap(
                test_session,
                test_principal,
                "unauthorized-component",
                None,
                None,
            )
        assert exc_info.value.code == "COMPONENT_NOT_PERMITTED"
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_any_component_when_no_restrictions(
        self,
        test_session,
        test_principal,
        test_profile_no_restrictions,
        test_manifest,
    ):
        """Should allow any component when allowed_components is empty."""
        binding = Binding(
            id=uuid4(),
            tenant_key="default",
            principal_id=test_principal.id,
            profile_id=test_profile_no_restrictions.id,
            manifest_id=test_manifest.id,
            active=True,
        )
        test_session.add(binding)
        await test_session.commit()

        packet, cached = await perform_bootstrap(
            test_session,
            test_principal,
            "any-component-name",
            None,
            None,
        )
        assert packet is not None
        assert packet.component_key == "any-component-name"


class TestETagCaching:
    """Tests for ETag-based caching."""

    @pytest.mark.asyncio
    async def test_returns_304_with_matching_etag(
        self,
        test_session,
        test_principal,
        test_profile,
        test_manifest,
        test_binding,
    ):
        """Should return cached=True when ETag matches."""
        packet1, _ = await perform_bootstrap(
            test_session,
            test_principal,
            "allowed-component",
            None,
            None,
        )

        packet2, cached = await perform_bootstrap(
            test_session,
            test_principal,
            "allowed-component",
            None,
            packet1.packet_etag,
        )

        assert packet2 is None
        assert cached is True


class TestBootstrapFlow:
    """Tests for complete bootstrap flow."""

    @pytest.mark.asyncio
    async def test_no_binding_returns_403(self, test_session, test_principal):
        """Should return 403 when principal has no active binding."""
        with pytest.raises(BootstrapError) as exc_info:
            await perform_bootstrap(
                test_session,
                test_principal,
                "some-component",
                None,
                None,
            )
        assert exc_info.value.code == "NO_BINDING"
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_principal_mismatch_returns_409(
        self,
        test_session,
        test_principal,
        test_binding,
    ):
        """Should return 409 when principal_key hint does not match."""
        with pytest.raises(BootstrapError) as exc_info:
            await perform_bootstrap(
                test_session,
                test_principal,
                "allowed-component",
                "wrong-principal-key",
                None,
            )
        assert exc_info.value.code == "PRINCIPAL_MISMATCH"
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_creates_startup_session(
        self,
        test_session,
        test_principal,
        test_profile,
        test_manifest,
        test_binding,
    ):
        """Should create a startup session with OPEN status."""
        packet, _ = await perform_bootstrap(
            test_session,
            test_principal,
            "allowed-component",
            None,
            None,
        )

        assert packet.startup is not None
        assert packet.startup.status == "OPEN"
        assert packet.startup.startup_id is not None


class TestRetentionCleanup:
    """Tests for session retention cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_ready_sessions(self, test_session):
        """Should delete sessions past retention period."""
        old_session = StartupSession(
            id=uuid4(),
            tenant_key="default",
            deployment_key="default",
            subject_principal_key="test-principal",
            component_key="test-component",
            profile_key="test-profile",
            manifest_key="test-manifest",
            packet_etag="etag123",
            packet_hash_redacted="hash123",
            status="READY",
            opened_at=datetime.now(timezone.utc) - timedelta(hours=100),
            created_at=datetime.now(timezone.utc) - timedelta(hours=100),
        )
        test_session.add(old_session)
        await test_session.commit()

        deleted = await cleanup_old_sessions(test_session, retention_hours=72)
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_cleanup_preserves_open_sessions(self, test_session):
        """Should not delete sessions in OPEN status."""
        old_session = StartupSession(
            id=uuid4(),
            tenant_key="default",
            deployment_key="default",
            subject_principal_key="test-principal",
            component_key="test-component",
            profile_key="test-profile",
            manifest_key="test-manifest",
            packet_etag="etag123",
            packet_hash_redacted="hash123",
            status="OPEN",
            opened_at=datetime.now(timezone.utc) - timedelta(hours=100),
            created_at=datetime.now(timezone.utc) - timedelta(hours=100),
        )
        test_session.add(old_session)
        await test_session.commit()

        deleted = await cleanup_old_sessions(test_session, retention_hours=72)
        assert deleted == 0
