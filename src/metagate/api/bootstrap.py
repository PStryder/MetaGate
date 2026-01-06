"""Bootstrap API endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..auth.auth import get_authenticated_principal, AuthenticatedPrincipal
from ..services.bootstrap import perform_bootstrap, BootstrapError, ForbiddenKeyError
from ..models.schemas import BootstrapRequest, WelcomePacket, ErrorResponse

router = APIRouter(prefix="/v1", tags=["bootstrap"])


@router.post(
    "/bootstrap",
    response_model=WelcomePacket,
    responses={
        200: {"description": "Welcome Packet returned"},
        304: {"description": "Not Modified - packet unchanged"},
        403: {"description": "Forbidden - no binding or permission denied"},
        409: {"description": "Conflict - principal key mismatch"},
    },
    summary="Bootstrap a component",
    description="Authenticates caller, resolves identity, and returns a Welcome Packet",
)
async def bootstrap(
    request: BootstrapRequest,
    response: Response,
    auth: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: AsyncSession = Depends(get_db),
):
    """
    Bootstrap endpoint per spec section 7.2.

    Authenticates callers, resolves identity -> binding -> profile -> manifest,
    and returns a Welcome Packet with an OPEN startup receipt.
    """
    try:
        packet, is_cached = await perform_bootstrap(
            db=db,
            principal=auth.principal,
            component_key=request.component_key,
            principal_key_hint=request.principal_key,
            last_packet_etag=request.last_packet_etag,
        )

        if is_cached:
            response.status_code = 304
            return Response(status_code=304)

        # Set ETag header
        response.headers["ETag"] = packet.packet_etag

        return packet

    except ForbiddenKeyError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except BootstrapError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
