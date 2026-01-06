"""Startup session management service."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional, Any

from ..models.db_models import StartupSession
from ..models.schemas import StartupAckResponse


class StartupError(Exception):
    """Base error for startup operations."""

    def __init__(self, message: str, status_code: int = 500, code: str = "STARTUP_ERROR"):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


async def get_startup_session(
    db: AsyncSession,
    startup_id: UUID
) -> Optional[StartupSession]:
    """Get a startup session by ID."""
    result = await db.execute(
        select(StartupSession).where(StartupSession.id == startup_id)
    )
    return result.scalar_one_or_none()


async def mark_startup_ready(
    db: AsyncSession,
    startup_id: UUID,
    build_version: str,
    health: Optional[str] = None,
) -> StartupAckResponse:
    """Mark a startup session as READY."""
    session = await get_startup_session(db, startup_id)

    if not session:
        raise StartupError(
            f"Startup session {startup_id} not found",
            status_code=404,
            code="SESSION_NOT_FOUND"
        )

    if session.status != "OPEN":
        raise StartupError(
            f"Startup session {startup_id} is not OPEN (status={session.status})",
            status_code=409,
            code="INVALID_STATE"
        )

    now = datetime.now(timezone.utc)

    session.status = "READY"
    session.ready_at = now
    session.ready_payload = {
        "build_version": build_version,
        "health": health,
        "acknowledged_at": now.isoformat(),
    }

    await db.commit()
    await db.refresh(session)

    return StartupAckResponse(
        startup_id=session.id,
        status=session.status,
        acknowledged_at=now,
    )


async def mark_startup_failed(
    db: AsyncSession,
    startup_id: UUID,
    error: str,
    details: Optional[dict[str, Any]] = None,
) -> StartupAckResponse:
    """Mark a startup session as FAILED."""
    session = await get_startup_session(db, startup_id)

    if not session:
        raise StartupError(
            f"Startup session {startup_id} not found",
            status_code=404,
            code="SESSION_NOT_FOUND"
        )

    if session.status != "OPEN":
        raise StartupError(
            f"Startup session {startup_id} is not OPEN (status={session.status})",
            status_code=409,
            code="INVALID_STATE"
        )

    now = datetime.now(timezone.utc)

    session.status = "FAILED"
    session.failed_at = now
    session.failure_payload = {
        "error": error,
        "details": details or {},
        "acknowledged_at": now.isoformat(),
    }

    await db.commit()
    await db.refresh(session)

    return StartupAckResponse(
        startup_id=session.id,
        status=session.status,
        acknowledged_at=now,
    )


async def get_startup_status(
    db: AsyncSession,
    startup_id: UUID
) -> Optional[dict[str, Any]]:
    """Get the current status of a startup session."""
    session = await get_startup_session(db, startup_id)

    if not session:
        return None

    return {
        "startup_id": session.id,
        "status": session.status,
        "component_key": session.component_key,
        "principal_key": session.subject_principal_key,
        "opened_at": session.opened_at,
        "deadline_at": session.deadline_at,
        "ready_at": session.ready_at,
        "failed_at": session.failed_at,
    }
