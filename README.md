# MetaGate v0

**Meta configuration authority and bootstrap witness for LegiVellum-compatible systems**

> MetaGate is the first flame. MetaGate is truth, not control.

## Overview

MetaGate is a non-blocking, describe-only bootstrap authority that provides world truth to components before they participate in a distributed system.

### What MetaGate Does

- Authenticates callers
- Resolves identity → binding → profile → manifest
- Returns a Welcome Packet describing the environment
- Issues a startup OPEN receipt as a witness of bootstrap

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

# Check health
curl http://localhost:8000/health

# View discovery endpoint
curl http://localhost:8000/.well-known/metagate.json
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
curl -X POST http://localhost:8000/v1/bootstrap \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"component_key": "memorygate_main"}'

# Using JWT
python scripts/generate_jwt.py test-subject-001
# Use the token from the output
curl -X POST http://localhost:8000/v1/bootstrap \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"component_key": "memorygate_main"}'
```

## API Endpoints

### Discovery
- `GET /.well-known/metagate.json` - Service discovery

### Bootstrap
- `POST /v1/bootstrap` - Bootstrap a component, returns Welcome Packet

### Startup Lifecycle
- `POST /v1/startup/ready` - Component reports successful initialization
- `POST /v1/startup/failed` - Component reports startup failure

### Admin (CRUD)
- `POST/GET/DELETE /v1/admin/principals` - Manage principals
- `POST/GET/DELETE /v1/admin/profiles` - Manage profiles
- `POST/GET/DELETE /v1/admin/manifests` - Manage manifests
- `POST/GET/DELETE /v1/admin/bindings` - Manage bindings
- `POST/GET/DELETE /v1/admin/secret-refs` - Manage secret references

### Health
- `GET /health` - Health check
- `GET /` - Root info

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://metagate:metagate@db:5432/metagate` | Database connection |
| `JWT_SECRET` | `change-me-in-production` | JWT signing secret |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ISSUER` | (none) | Optional JWT issuer validation |
| `API_KEY_HEADER` | `X-API-Key` | API key header name |
| `DEBUG` | `false` | Enable debug logging |
| `METAGATE_VERSION` | `0.1` | API version |
| `DEFAULT_STARTUP_SLA_SECONDS` | `120` | Default startup SLA |
| `RECEIPT_RETENTION_HOURS` | `72` | Receipt retention period |

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
Ties: `principal → profile + manifest (+ overrides)`. Exactly one active binding per principal in v0.

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
      "POST /v1/startup/ready",
      "POST /v1/startup/failed"
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
