# MetaGate v0

**Meta configuration authority and bootstrap witness for LegiVellum-compatible systems**

> MetaGate is the first flame. MetaGate is truth, not control.

## Overview

MetaGate is a non-blocking, describe-only bootstrap authority that provides world truth to components before they participate in a distributed system.

### What MetaGate Does

- Authenticates callers
- Resolves identity -> binding -> profile -> manifest
- Returns a Welcome Packet describing the environment
- Issues startup lifecycle receipts to ReceiptGate (when configured)

### What MetaGate Never Does

- Assigns work
- Provisions infrastructure
- Waits on other services
- Orchestrates execution
- Blocks on health checks
- Distributes task payloads

## Quick Start

### Using Docker Compose

```bash
# Start MetaGate and PostgreSQL
docker-compose up -d

# Or use the one-command script
./run_local.sh

# Check health
curl -s http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"metagate.health","arguments":{}}}'

# View discovery info
curl -s http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"metagate.discovery","arguments":{}}}'
```

### Seed Test Data

```bash
# Install dependencies locally (for running seed script)
pip install asyncpg python-jose

# Run seed script
python scripts/seed_data.py
```

The seed script will output an API key you can use for testing.

### Test Bootstrap

```bash
# Using API Key (from seed script output)
curl -X POST http://localhost:8000/mcp \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"metagate.bootstrap","arguments":{"component_key":"memorygate_main"}}}'

# Using JWT
python scripts/generate_jwt.py test-subject-001
# Use the token from the output
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"metagate.bootstrap","arguments":{"component_key":"memorygate_main"}}}'
```

## MCP Tools

MetaGate exposes MCP over HTTP at `/mcp` with JSON-RPC methods:
- `tools/list`
- `tools/call`

**Core tools:**
- `metagate.discovery` - Service discovery
- `metagate.health` - Health check / service info
- `metagate.bootstrap` - Bootstrap a component, returns Welcome Packet
- `metagate.startup_ready` - Component reports successful initialization
- `metagate.startup_failed` - Component reports startup failure

**Admin tools:**
- `metagate.admin_principals` - Manage principals
- `metagate.admin_profiles` - Manage profiles
- `metagate.admin_manifests` - Manage manifests
- `metagate.admin_bindings` - Manage bindings
- `metagate.admin_secret_refs` - Manage secret references
- `metagate.admin_api_keys` - Issue, list, and revoke API keys. A key's plaintext is returned once at issue and never stored; revocation marks status rather than deleting the row, so an audit trail survives.

**Topology:**
- `metagate.instantiate_problemata` - Instantiate a validated Problemata into a live topology. Refuses anything whose `validation.status` is not `passed`: MetaGate describes topology, it does not repair it.

## Configuration

Environment variables (prefix `METAGATE_`). Generated from the `Settings`
class; MetaGate bootstrap variables are documented in their own section below.

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_DEBUG` | `false` | Enable debug mode |
| `METAGATE_HOST` | `0.0.0.0` | Server bind address |
| `METAGATE_METAGATE_VERSION` | `0.1` | MetaGate version reported in discovery and bootstrap responses. The doubled prefix is real: the field is named `metagate_version` and the env prefix is `METAGATE_` |
| `METAGATE_INSTANCE_ID` | `metagate-1` | Instance identifier |
| `METAGATE_PORT` | `8000` | Server port |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_DATABASE_URL` | `postgresql+asyncpg://metagate:metagate@db:5432/metagate` | Database connection URL |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_ADMIN_ALLOW_CROSS_TENANT` | `false` | Allow admin operations across tenants |
| `METAGATE_ADMIN_PRINCIPAL_KEYS` | *(empty)* | Explicit principal keys allowed to access admin tools |
| `METAGATE_ADMIN_PRINCIPAL_TYPES` | `['admin']` | Principal types allowed to access admin tools |
| `METAGATE_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `METAGATE_JWT_ISSUER` | *(unset)* | JWT issuer |
| `METAGATE_JWT_SECRET` | `change-me-in-production` | JWT secret key |

### Upstream services

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_RECEIPTGATE_AUTH_TOKEN` | *(empty)* | ReceiptGate auth token |
| `METAGATE_RECEIPTGATE_EMIT_RECEIPTS` | `true` | Emit startup receipts to ReceiptGate |
| `METAGATE_RECEIPTGATE_ENDPOINT` | *(empty)* | ReceiptGate MCP endpoint |

### Rate limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `METAGATE_RATE_LIMIT_REQUESTS_PER_MINUTE` | `100` | Rate limit per minute |

### CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials in CORS requests |
| `METAGATE_CORS_ALLOWED_HEADERS` | `['Authorization', 'Content-Type', 'X-Tenant-ID']` | Allowed request headers |
| `METAGATE_CORS_ALLOWED_METHODS` | `['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']` | Allowed HTTP methods |
| `METAGATE_CORS_ALLOWED_ORIGINS` | `['http://localhost:3000', 'http://localhost:8080']` | Allowed CORS origins (explicit allowlist for security) |

### Behaviour and limits

| Variable | Default | Description |
|----------|---------|-------------|
| `METAGATE_API_KEY_HEADER` | `X-API-Key` | API key header name |
| `METAGATE_DEFAULT_DEPLOYMENT_KEY` | `default` | Default deployment key |
| `METAGATE_DEFAULT_STARTUP_SLA_SECONDS` | `120` | Default startup SLA in seconds |
| `METAGATE_DEFAULT_TENANT_KEY` | `default` | Default tenant key |
| `METAGATE_RECEIPT_RETENTION_HOURS` | `72` | Receipt retention in hours |

## Core Concepts

### Principal
A principal is *who is speaking*. Identified by auth subject, maps to a stable `principal_key`.

### Component
A component is *what is being instantiated*. Examples: `memorygate_main`, `asyncgate_default`, `worker_indexer_01`.

### Profile
Defines capabilities, policy constraints, startup SLA defaults, and secret handling rules. Answers: "What kind of thing is this?"

### Manifest
Describes the world: services, endpoints, auth expectations, memory gate usage, polling locations, schema references. Answers: "What world am I in?"

### Binding
Ties: `principal -> profile + manifest (+ overrides)`. Exactly one active binding per principal in v0.

## Welcome Packet Schema

```json
{
  "packet_id": "uuid",
  "packet_etag": "string",
  "issued_at": "timestamp",
  "principal_key": "string",
  "component_key": "string",
  "profile": "string",
  "manifest": "string",
  "capabilities": {},
  "policy": {},
  "services": {},
  "memory_map": {},
  "polling": {},
  "schemas": {},
  "required_env": [],
  "startup": {
    "startup_id": "uuid",
    "status": "OPEN",
    "deadline_at": "timestamp",
    "followup": [
      "metagate.startup_ready",
      "metagate.startup_failed"
    ]
  }
}
```

## Startup Lifecycle

1. **OPEN** - Issued by MetaGate when Welcome Packet is returned
2. **READY** - Issued by component when listening + initialized
3. **FAILED** - Issued by component if startup aborts

Absence of READY past SLA is meaningful state.

## Forbidden Keys

Manifests and packets must not contain: `tasks`, `jobs`, `work_items`, `payloads`, `deploy`, `scale`, `provision`, `execute`.

Violation results in write-time rejection.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run locally (requires PostgreSQL)
uvicorn metagate.main:app --reload

# Run tests
pytest

# Type checking
mypy src/metagate

# Linting
ruff check src/
```

## License

MIT
