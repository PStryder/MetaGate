"""Discovery endpoint - /.well-known/metagate.json"""
from fastapi import APIRouter

from ..config import get_settings
from ..models.schemas import DiscoveryResponse

router = APIRouter()
settings = get_settings()


@router.get(
    "/.well-known/metagate.json",
    response_model=DiscoveryResponse,
    tags=["discovery"],
    summary="MetaGate Discovery",
    description="Returns MetaGate service discovery information",
)
async def get_discovery():
    """
    Discovery endpoint per spec section 7.1.

    Returns service version, bootstrap endpoint, and supported auth methods.
    """
    return DiscoveryResponse(
        metagate_version=settings.metagate_version,
        bootstrap_endpoint="/v1/bootstrap",
        supported_auth=["jwt", "api_key"],
    )
