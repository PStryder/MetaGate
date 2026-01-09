"""Tests for startup lifecycle service."""
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from metagate.services.startup import (
    mark_startup_ready,
    mark_startup_failed,
    get_startup_status,
    StartupError,
)
from metagate.models.db_models import StartupSession


@pytest.fixture
async def open_session(test_session) -> StartupSession:
    """Create an OPEN startup session for testing."""
    session = StartupSession(
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
        opened_at=datetime.now(timezone.utc),
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    test_session.add(session)
    await test_session.commit()
    await test_session.refresh(session)
    return session


class TestMarkStartupReady:
    """Tests for marking startup as READY."""

    @pytest.mark.asyncio
    async def test_mark_open_session_ready(self, test_session, open_session):
        """Should transition OPEN session to READY."""
        result = await mark_startup_ready(
            test_session,
            open_session.id,
            build_version="1.0.0",
            health="healthy",
        )

        assert result.status == "READY"
        assert result.startup_id == open_session.id

    @pytest.mark.asyncio
    async def test_cannot_mark_ready_twice(self, test_session, open_session):
        """Should fail to mark already-READY session as READY."""
        await mark_startup_ready(
            test_session,
            open_session.id,
            build_version="1.0.0",
        )

        with pytest.raises(StartupError) as exc_info:
            await mark_startup_ready(
                test_session,
                open_session.id,
                build_version="1.0.0",
            )
        assert exc_info.value.code == "INVALID_STATE"

    @pytest.mark.asyncio
    async def test_not_found_session(self, test_session):
        """Should fail for non-existent session."""
        with pytest.raises(StartupError) as exc_info:
            await mark_startup_ready(
                test_session,
                uuid4(),
                build_version="1.0.0",
            )
        assert exc_info.value.code == "SESSION_NOT_FOUND"
        assert exc_info.value.status_code == 404


class TestMarkStartupFailed:
    """Tests for marking startup as FAILED."""

    @pytest.mark.asyncio
    async def test_mark_open_session_failed(self, test_session, open_session):
        """Should transition OPEN session to FAILED."""
        result = await mark_startup_failed(
            test_session,
            open_session.id,
            error="Initialization error",
            details={"reason": "timeout"},
        )

        assert result.status == "FAILED"
        assert result.startup_id == open_session.id

    @pytest.mark.asyncio
    async def test_cannot_fail_ready_session(self, test_session, open_session):
        """Should fail to mark READY session as FAILED."""
        await mark_startup_ready(
            test_session,
            open_session.id,
            build_version="1.0.0",
        )

        with pytest.raises(StartupError) as exc_info:
            await mark_startup_failed(
                test_session,
                open_session.id,
                error="Late failure",
            )
        assert exc_info.value.code == "INVALID_STATE"


class TestGetStartupStatus:
    """Tests for getting startup status."""

    @pytest.mark.asyncio
    async def test_get_existing_session(self, test_session, open_session):
        """Should return status for existing session."""
        status = await get_startup_status(test_session, open_session.id)

        assert status is not None
        assert status["status"] == "OPEN"
        assert status["component_key"] == "test-component"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, test_session):
        """Should return None for non-existent session."""
        status = await get_startup_status(test_session, uuid4())
        assert status is None
