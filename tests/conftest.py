"""Pytest fixtures and configuration for MetaGate tests."""
import asyncio
import os
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

os.environ.setdefault("METAGATE_JWT_SECRET", "test-secret")
os.environ.setdefault("METAGATE_DEBUG", "true")
os.environ.setdefault("METAGATE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from metagate.database import Base
from metagate.main import app
from metagate.database import get_db
from metagate.models.db_models import Principal, Profile, Manifest, Binding, ApiKey
from metagate.auth.auth import hash_api_key


# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    TestSessionLocal = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client with test database."""
    TestSessionLocal = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # MCP routes use AsyncSessionLocal directly, so patch it to the test sessionmaker.
    import metagate.mcp.routes as mcp_routes
    mcp_routes.AsyncSessionLocal = TestSessionLocal

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_principal(test_session: AsyncSession) -> Principal:
    """Create a test principal."""
    principal = Principal(
        id=uuid4(),
        tenant_key="default",
        principal_key="test-principal-001",
        auth_subject="test-subject-001",
        principal_type="component",
        status="active",
    )
    test_session.add(principal)
    await test_session.commit()
    await test_session.refresh(principal)
    return principal


@pytest_asyncio.fixture
async def test_profile(test_session: AsyncSession) -> Profile:
    """Create a test profile with allowed_components restriction."""
    profile = Profile(
        id=uuid4(),
        tenant_key="default",
        profile_key="test-profile",
        capabilities={
            "memory_read": True,
            "memory_write": True,
            "allowed_components": ["allowed-component", "another-allowed"],
        },
        policy={"max_memory_mb": 1024},
        startup_sla_seconds=120,
    )
    test_session.add(profile)
    await test_session.commit()
    await test_session.refresh(profile)
    return profile


@pytest_asyncio.fixture
async def test_profile_no_restrictions(test_session: AsyncSession) -> Profile:
    """Create a test profile with no component restrictions."""
    profile = Profile(
        id=uuid4(),
        tenant_key="default",
        profile_key="test-profile-unrestricted",
        capabilities={"memory_read": True},
        policy={"max_memory_mb": 512},
        startup_sla_seconds=60,
    )
    test_session.add(profile)
    await test_session.commit()
    await test_session.refresh(profile)
    return profile


@pytest_asyncio.fixture
async def test_manifest(test_session: AsyncSession) -> Manifest:
    """Create a test manifest."""
    manifest = Manifest(
        id=uuid4(),
        tenant_key="default",
        manifest_key="test-manifest",
        deployment_key="test-deployment",
        environment={"stage": "test"},
        services={"memorygate": {"url": "http://memorygate:8001"}},
        memory_map={"primary": {"gate": "memorygate"}},
        polling={"asyncgate": {"interval_ms": 1000}},
        schemas={"version": "1.0"},
        version=1,
    )
    test_session.add(manifest)
    await test_session.commit()
    await test_session.refresh(manifest)
    return manifest


@pytest_asyncio.fixture
async def test_binding(
    test_session: AsyncSession,
    test_principal: Principal,
    test_profile: Profile,
    test_manifest: Manifest,
) -> Binding:
    """Create a test binding."""
    binding = Binding(
        id=uuid4(),
        tenant_key="default",
        principal_id=test_principal.id,
        profile_id=test_profile.id,
        manifest_id=test_manifest.id,
        active=True,
    )
    test_session.add(binding)
    await test_session.commit()
    await test_session.refresh(binding)
    return binding


@pytest_asyncio.fixture
async def test_api_key(
    test_session: AsyncSession,
    test_principal: Principal,
) -> tuple[str, ApiKey]:
    """Create a test API key and return both the raw key and the record."""
    raw_key = "test_api_key_12345"
    api_key = ApiKey(
        id=uuid4(),
        tenant_key="default",
        key_hash=hash_api_key(raw_key),
        principal_id=test_principal.id,
        name="Test API Key",
        status="active",
    )
    test_session.add(api_key)
    await test_session.commit()
    await test_session.refresh(api_key)
    return raw_key, api_key
