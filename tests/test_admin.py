"""Tests for admin API endpoints."""
import pytest


class TestAdminEndpoints:
    """Tests for admin CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_principals_requires_auth(self, client):
        """Should require authentication for admin endpoints."""
        response = await client.get("/v1/admin/principals")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Health endpoint should be accessible."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "MetaGate"

    @pytest.mark.asyncio
    async def test_discovery_endpoint(self, client):
        """Discovery endpoint should return MetaGate info."""
        response = await client.get("/.well-known/metagate.json")
        assert response.status_code == 200
        data = response.json()
        assert "metagate_version" in data
        assert "bootstrap_endpoint" in data

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        """Root endpoint should return service info."""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "MetaGate"
        assert "doctrine" in data


class TestBootstrapEndpoint:
    """Tests for bootstrap API endpoint."""

    @pytest.mark.asyncio
    async def test_bootstrap_requires_auth(self, client):
        """Should require authentication for bootstrap."""
        response = await client.post(
            "/v1/bootstrap",
            json={"component_key": "test-component"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_bootstrap_validates_component_key(self, client):
        """Should validate component_key is required."""
        response = await client.post(
            "/v1/bootstrap",
            json={},
        )
        assert response.status_code in [401, 422]


class TestStartupEndpoints:
    """Tests for startup lifecycle endpoints."""

    @pytest.mark.asyncio
    async def test_startup_ready_requires_auth(self, client):
        """Should require authentication for startup ready."""
        response = await client.post(
            "/v1/startup/ready",
            json={
                "startup_id": "00000000-0000-0000-0000-000000000000",
                "build_version": "1.0.0",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_startup_failed_requires_auth(self, client):
        """Should require authentication for startup failed."""
        response = await client.post(
            "/v1/startup/failed",
            json={
                "startup_id": "00000000-0000-0000-0000-000000000000",
                "error": "Test error",
            },
        )
        assert response.status_code == 401
