#!/usr/bin/env python3
"""
Seed script for MetaGate development.

Creates initial test data including:
- A test principal
- A test profile
- A test manifest
- A binding connecting them
- An API key for testing

Run with: python scripts/seed_data.py
"""
import asyncio
import hashlib
import secrets
from uuid import uuid4
from datetime import datetime, timezone

import asyncpg


async def main():
    # Connect to database
    conn = await asyncpg.connect(
        "postgresql://metagate:metagate@localhost:5432/metagate"
    )

    try:
        print("Seeding MetaGate database...")

        # Create test principal
        principal_id = uuid4()
        principal_key = "test-component-001"
        auth_subject = "test-subject-001"

        await conn.execute("""
            INSERT INTO principals (id, tenant_key, principal_key, auth_subject, principal_type, status)
            VALUES ($1, 'default', $2, $3, 'component', 'active')
            ON CONFLICT (principal_key) DO NOTHING
        """, principal_id, principal_key, auth_subject)
        print(f"Created principal: {principal_key}")

        # Create test profile
        profile_id = uuid4()
        profile_key = "default-profile"
        capabilities = {
            "memory_read": True,
            "memory_write": True,
            "async_poll": True,
        }
        policy = {
            "max_memory_mb": 1024,
            "rate_limit_rps": 100,
        }

        await conn.execute("""
            INSERT INTO profiles (id, tenant_key, profile_key, capabilities, policy, startup_sla_seconds)
            VALUES ($1, 'default', $2, $3, $4, 120)
            ON CONFLICT (profile_key) DO NOTHING
        """, profile_id, profile_key, str(capabilities).replace("'", '"').replace("True", "true").replace("False", "false"),
             str(policy).replace("'", '"'))
        print(f"Created profile: {profile_key}")

        # Create test manifest
        manifest_id = uuid4()
        manifest_key = "default-manifest"
        environment = {"stage": "development", "region": "local"}
        services = {
            "memorygate": {"url": "http://memorygate:8001", "auth": "jwt"},
            "asyncgate": {"url": "http://asyncgate:8002", "auth": "jwt"},
        }
        memory_map = {
            "primary": {"gate": "memorygate", "namespace": "default"},
        }
        polling = {
            "asyncgate": {"endpoint": "/mcp", "interval_ms": 1000},
        }
        schemas = {
            "memory_schema_version": "1.0",
        }

        import json

        await conn.execute("""
            INSERT INTO manifests (id, tenant_key, manifest_key, deployment_key, environment, services, memory_map, polling, schemas, version)
            VALUES ($1, 'default', $2, 'default', $3, $4, $5, $6, $7, 1)
            ON CONFLICT (manifest_key) DO NOTHING
        """, manifest_id, manifest_key, json.dumps(environment), json.dumps(services),
             json.dumps(memory_map), json.dumps(polling), json.dumps(schemas))
        print(f"Created manifest: {manifest_key}")

        # Fetch IDs (in case they already existed)
        row = await conn.fetchrow("SELECT id FROM principals WHERE principal_key = $1", principal_key)
        principal_id = row['id']

        row = await conn.fetchrow("SELECT id FROM profiles WHERE profile_key = $1", profile_key)
        profile_id = row['id']

        row = await conn.fetchrow("SELECT id FROM manifests WHERE manifest_key = $1", manifest_key)
        manifest_id = row['id']

        # Create binding
        binding_id = uuid4()
        await conn.execute("""
            INSERT INTO bindings (id, tenant_key, principal_id, profile_id, manifest_id, active)
            VALUES ($1, 'default', $2, $3, $4, true)
            ON CONFLICT DO NOTHING
        """, binding_id, principal_id, profile_id, manifest_id)
        print(f"Created binding for principal {principal_key}")

        # Generate API key
        api_key = f"mgk_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        await conn.execute("""
            INSERT INTO api_keys (id, tenant_key, key_hash, principal_id, name, status)
            VALUES ($1, 'default', $2, $3, 'Test API Key', 'active')
            ON CONFLICT (key_hash) DO NOTHING
        """, uuid4(), key_hash, principal_id)

        print("\n" + "="*60)
        print("SEED DATA CREATED SUCCESSFULLY")
        print("="*60)
        print(f"\nPrincipal Key: {principal_key}")
        print(f"Auth Subject: {auth_subject}")
        print(f"Profile: {profile_key}")
        print(f"Manifest: {manifest_key}")
        print(f"\nAPI Key (save this - shown only once):")
        print(f"  {api_key}")
        print("\nTest bootstrap with:")
        print(f'  curl -X POST http://localhost:8000/mcp \\')
        print(f'    -H "X-API-Key: {api_key}" \\')
        print(f'    -H "Content-Type: application/json" \\')
        print('    -d \'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"metagate.bootstrap","arguments":{"component_key":"memorygate_main"}}}\'')
        print("="*60)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
