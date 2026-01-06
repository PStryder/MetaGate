"""MetaGate - Bootstrap authority for LegiVellum-compatible systems.

MetaGate is the first flame.

MetaGate is a non-blocking, describe-only bootstrap authority that provides
world truth to components before they participate in a distributed system.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .config import get_settings
from .api.discovery import router as discovery_router
from .api.bootstrap import router as bootstrap_router
from .api.startup import router as startup_router
from .api.admin import router as admin_router

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("metagate")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"MetaGate v{settings.metagate_version} starting...")
    logger.info("MetaGate is the first flame. MetaGate is truth, not control.")
    yield
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# Include routers
app.include_router(discovery_router)
app.include_router(bootstrap_router)
app.include_router(startup_router)
app.include_router(admin_router)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.metagate_version}


@app.get("/", tags=["root"])
async def root():
    """Root endpoint with basic info."""
    return {
        "service": "MetaGate",
        "version": settings.metagate_version,
        "doctrine": "MetaGate is truth, not control.",
        "discovery": "/.well-known/metagate.json",
    }
