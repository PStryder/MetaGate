"""Startup session API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..auth.auth import get_authenticated_principal, AuthenticatedPrincipal
from ..services.startup import mark_startup_ready, mark_startup_failed, StartupError
from ..models.schemas import (
    StartupReadyRequest,
    StartupFailedRequest,
    StartupAckResponse,
)

router = APIRouter(prefix="/v1/startup", tags=["startup"])


@router.post(
    "/ready",
    response_model=StartupAckResponse,
    responses={
        200: {"description": "Startup marked as ready"},
        404: {"description": "Startup session not found"},
        409: {"description": "Invalid state transition"},
    },
    summary="Mark startup as ready",
    description="Component reports successful initialization",
)
async def startup_ready(
    request: StartupReadyRequest,
    auth: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    Startup ready endpoint per spec section 7.3.

    Components call this when they are listening and initialized.
    """
    try:
        return await mark_startup_ready(
            db=db,
            startup_id=request.startup_id,
            build_version=request.build_version,
            health=request.health,
        )
    except StartupError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post(
    "/failed",
    response_model=StartupAckResponse,
    responses={
        200: {"description": "Startup marked as failed"},
        404: {"description": "Startup session not found"},
        409: {"description": "Invalid state transition"},
    },
    summary="Mark startup as failed",
    description="Component reports startup failure",
)
async def startup_failed(
    request: StartupFailedRequest,
    auth: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    Startup failed endpoint per spec section 7.4.

    Components call this if startup aborts.
    """
    try:
        return await mark_startup_failed(
            db=db,
            startup_id=request.startup_id,
            error=request.error,
            details=request.details,
        )
    except StartupError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
