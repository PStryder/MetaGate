"""MetaGate - Bootstrap authority for LegiVellum-compatible systems.

MetaGate is the first flame.

MetaGate is a non-blocking, describe-only bootstrap authority that provides
world truth to components before they participate in a distributed system.
"""
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging

from .config import get_settings
from .api.discovery import router as discovery_router
from .api.bootstrap import router as bootstrap_router
from .api.startup import router as startup_router
from .api.admin import router as admin_router
from .middleware import get_rate_limiter
from .services.bootstrap import cleanup_old_sessions
from .database import AsyncSessionLocal

settings = get_settings()


# Rate limiting dependency
async def rate_limit_dependency(request: Request) -> None:
    """Rate limiting dependency."""
    limiter = get_rate_limiter(
        calls_per_minute=settings.rate_limit_requests_per_minute,
        enabled=settings.rate_limit_enabled
    )
    await limiter.check_request(request)


# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("metagate")


async def retention_cleanup_task():
    """Background task that periodically cleans up old startup sessions."""
    cleanup_interval = 3600  # Run every hour
    while True:
        try:
            await asyncio.sleep(cleanup_interval)
            async with AsyncSessionLocal() as db:
                deleted = await cleanup_old_sessions(db, settings.receipt_retention_hours)
                if deleted > 0:
                    logger.info(f"Retention cleanup: deleted {deleted} old startup sessions")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Retention cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"MetaGate v{settings.metagate_version} starting...")
    logger.info("MetaGate is the first flame. MetaGate is truth, not control.")
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(retention_cleanup_task())
    
    yield
    
    # Cancel cleanup task on shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    logger.info("MetaGate shutting down...")


app = FastAPI(
    title="MetaGate",
    description="""
MetaGate - Meta configuration authority and bootstrap witness for LegiVellum-compatible systems.

## Purpose

MetaGate is a non-blocking, describe-only bootstrap authority that provides world truth
to components before they participate in a distributed system.

## What MetaGate Does

- Authenticates callers
- Resolves identity → binding → profile → manifest
- Returns a Welcome Packet describing the environment
- Issues a startup OPEN receipt as a witness of bootstrap

## What MetaGate Never Does

- Assigns work
- Provisions infrastructure
- Waits on other services
- Orchestrates execution
- Blocks on health checks
- Distributes task payloads

MetaGate is truth, not control.
    """,
    version=settings.metagate_version,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allowed_methods,
    allow_headers=settings.cors_allowed_headers,
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# Include routers (with rate limiting)
app.include_router(discovery_router, dependencies=[Depends(rate_limit_dependency)])
app.include_router(bootstrap_router, dependencies=[Depends(rate_limit_dependency)])
app.include_router(startup_router, dependencies=[Depends(rate_limit_dependency)])
app.include_router(admin_router, dependencies=[Depends(rate_limit_dependency)])


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "MetaGate",
        "version": settings.metagate_version,
        "instance_id": settings.instance_id
    }


@app.get("/", tags=["root"])
async def root():
    """Root endpoint with basic info."""
    return {
        "service": "MetaGate",
        "version": settings.metagate_version,
        "doctrine": "MetaGate is truth, not control.",
        "discovery": "/.well-known/metagate.json",
    }
