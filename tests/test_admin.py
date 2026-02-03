"""Tests for admin API endpoints."""
import pytest


class TestAdminEndpoints:
    """Tests for admin CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_principals_requires_auth(self, client):
        """Should require authentication for admin tools."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "metagate.admin_principals", "arguments": {}},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "auth" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        """Health tool should be accessible."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "metagate.health", "arguments": {}},
            },
        )
        assert response.status_code == 200
        data = response.json()["result"]
        assert data["status"] == "healthy"
        assert data["service"] == "MetaGate"

    @pytest.mark.asyncio
    async def test_discovery_endpoint(self, client):
        """Discovery tool should return MetaGate info."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "metagate.discovery", "arguments": {}},
            },
        )
        assert response.status_code == 200
        data = response.json()["result"]
        assert "metagate_version" in data
        assert "bootstrap_endpoint" in data


class TestBootstrapEndpoint:
    """Tests for bootstrap API endpoint."""

    @pytest.mark.asyncio
    async def test_bootstrap_requires_auth(self, client):
        """Should require authentication for bootstrap."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "metagate.bootstrap",
                    "arguments": {"component_key": "test-component"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "auth" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_bootstrap_validates_component_key(self, client, test_api_key):
        """Should validate component_key is required."""
        api_key, _ = test_api_key
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "metagate.bootstrap",
                    "arguments": {"auth_token": api_key},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "component_key" in data["error"]["message"]


class TestStartupEndpoints:
    """Tests for startup lifecycle endpoints."""

    @pytest.mark.asyncio
    async def test_startup_ready_requires_auth(self, client):
        """Should require authentication for startup ready."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "metagate.startup_ready",
                    "arguments": {
                        "startup_id": "00000000-0000-0000-0000-000000000000",
                        "build_version": "1.0.0",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "auth" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_startup_failed_requires_auth(self, client):
        """Should require authentication for startup failed."""
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "metagate.startup_failed",
                    "arguments": {
                        "startup_id": "00000000-0000-0000-0000-000000000000",
                        "error": "Test error",
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "auth" in data["error"]["message"].lower()
