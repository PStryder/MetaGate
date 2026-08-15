<!-- Generated 2026-08-15. Stack-level context: ../LV_STACK_REVIEW.md -->

> **Review 2 — MetaGate**
> Part of a full-stack review of LV_Stack (11 repos, ~97k LOC) conducted 2026-08-15.
> Stack-wide findings that affect this repo but are not fixable inside it are in
> `../LV_STACK_REVIEW.md` and `../_CROSS_REPO_ANALYSIS.md`. Read the stack report first —
> several findings below have a shared root cause.

---

# MetaGate — Code Review

Repo: `/home/claude/lv/MetaGate/` · ~4.7k LOC · role: system warden (bootstrap, topology, lifecycle)
Reviewed against: `MetaGate v0 Specification.txt`, `LegiVellum/docs/canonical/MetaGate/`,
`LegiVellum/docs/canonical/metagate.bootstrap.md`, `receipt.rules.md`, `receipt.schema.v1.json`,
`Gate v1 Exit Criteria Template.txt`.

## Verdict

The trust-root question has a bad answer: bootstrap is authenticated *inbound* but the Welcome Packet
carries no integrity protection and no gate authenticates MetaGate in return, so anything that can
answer on `metagate_endpoint` rewrites the whole mesh's `receiptgate_endpoint` and simultaneously
harvests every gate's MetaGate API key. Below that, the repo does not cold-start: `docker-compose.yml`
sets un-prefixed env vars that `Settings(env_prefix="METAGATE_")` never reads, so `run_local.sh` dies
in the config validator, and even past that the mounted `migrations/001_initial_schema.sql` lacks the
`created_by`/`updated_by` columns the ORM selects — which breaks *authentication itself* on a fresh DB.
Credential handling moved to bcrypt upstream (confirmed better than the vendored copy) but the verifier
does a full-table bcrypt scan per request, an unauthenticated CPU-exhaustion primitive on the service
every other gate must reach at startup. **Not v1-taggable.** Fix build/run, the auth scan, and startup-ack
ownership before anything else.

## Exit Criteria Scorecard

| § | Criterion | Score | Justification |
|---|---|---|---|
| 1 | Build & Run | **FAIL** | `docker-compose.yml:12-18` sets `DATABASE_URL`/`JWT_SECRET`/`DEBUG` without the `METAGATE_` prefix `config.py:14` requires ⇒ `validate_jwt_secret` raises at import; `run_local.sh` cannot start the stack. |
| 2 | API & Contract Stability | **PARTIAL** | MCP tool surface is stable and documented, but every error returns HTTP 200 with code `"ERROR"` — `routes.py:557-560` converts `BootstrapError` to `ValueError`, discarding the spec-mandated 403/409 distinction. |
| 3 | Canonical Principals | **FAIL** | No `SYSTEM_PRINCIPAL_ID` / `SERVICE_PRINCIPAL_ID` constants exist anywhere (grep: 0 hits); `receipts.py:97-98` uses the component's own principal for a MetaGate-internal obligation. |
| 4 | Receipt Model Invariants | **FAIL** | No `TERMINAL_RECEIPT_TYPES` set; `receipts.py:56` addresses the `accepted` receipt to `component_key` and the `complete` receipt to `subject_principal_key`, so the obligation never closes in the inbox it opened in; `caused_by_receipt_id` is always `"NA"` (`receipts.py:94`). |
| 5 | Persistence & Migration | **FAIL** | `migrations/001_initial_schema.sql` has no `created_by`/`updated_by`/`audit_log`; `docker-compose.yml:41` mounts only 001; no migration runner exists (alembic is a dependency with no `env.py`). Three divergent copies of the schema (001, 002, `k8s/postgresql-init-configmap.yaml`). |
| 6 | Core Behavioral Guarantees | **PARTIAL** | Golden path (bootstrap → OPEN → READY) is implemented and unit-tested, but no demo script, and `bootstrap.py:307` performs a 10 s-timeout network call inside the request, violating the §2 non-blocking hard invariant. |
| 7 | Test Requirements | **PARTIAL** | 8 test files, real coverage of forbidden keys / problemata derivation / key issuance; but zero tests for non-admin authz rejection, startup-ack ownership, cross-tenant instantiation, or receipt payload conformance. Tests build schema from ORM metadata (`conftest.py:47`), so migration drift is invisible. |
| 8 | Observability | **PARTIAL** | structlog + trace-id middleware is solid; but `services/audit.py` is entirely dead code (no caller), so the advertised audit trail does not exist. |
| 9 | v1 Lock Rules | **FAIL** | Cannot freeze receipt semantics or principal conventions that were never defined (§3, §4 above). |
| 10 | Open Issues / Deferred | **PARTIAL** | README documents describe-only boundaries and forbidden keys well; mirroring (spec §10) is silently a stub with no "deferred by design" statement in-repo. |

**Blunt verdict: NOT v1-taggable.** Two FAILs are hard blockers that make the documented quick start
impossible (§1, §5); two more are contract-level (§3, §4) and will force rework of every receipt MetaGate
emits after a v1 tag.

## Bootstrap Trust Analysis

**Is the bootstrap endpoint authenticated?** Yes, inbound. `routes.py:543-545` extracts a token and
`_authenticate` (`routes.py:212-223`) requires a JWT or API key resolving to an *active* principal before
any tool except `metagate.discovery` / `metagate.health` runs. `perform_bootstrap` then requires an active
binding (`bootstrap.py:209-215`) and verifies the `principal_key` hint against the authenticated principal
(`bootstrap.py:201-206`). That part is correct and matches spec §3.

**Can any caller register or mutate topology?** No, not directly — `routes.py:593-607` gates both
`metagate.instantiate_problemata` and every `metagate.admin_*` tool behind `is_admin_principal`. But there
is a cross-tenant hole (BT-2 below).

**Is there integrity on bootstrap payloads?** No. This is the central finding.

```python
# src/metagate/services/bootstrap.py:72-75
def generate_etag(data: dict[str, Any]) -> str:
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(content.encode()).hexdigest()
```

`packet_etag` is an unkeyed MD5 for cache revalidation. There is no signature, no MAC, no key material of
any kind on the Welcome Packet. Correspondingly, the shared client never verifies anything:

```python
# LegiVellum/shared/legivellum/metagate_bootstrap.py:121-134
url = endpoint if endpoint.endswith("/mcp") else f"{endpoint.rstrip('/')}/mcp"
headers = {"Content-Type": "application/json"}
if api_key:
    headers["X-API-Key"] = api_key
response = await client.post(url, json={...}, headers=headers)
```

The gate authenticates *itself to* MetaGate and takes whatever comes back on faith. Two consequences:

- **BT-1 (CRITICAL) — MetaGate impersonation rewrites the mesh.** Attacker capability: ability to answer on
  the address in `<PREFIX>METAGATE_ENDPOINT` (cluster DNS/service hijack, a malicious pod claiming the
  `metagate` Service selector label, a MITM on the plain-`http://` demo endpoints, or write access to one
  gate's env). Failure scenario: attacker returns a packet whose `services` contains
  `{"rg": {"type": "receiptgate", "endpoint": "http://attacker/mcp"}}`. `metagate_bootstrap.py:187-194`
  applies it because the operator left `receiptgate_endpoint` unset — which is the *documented normal case*
  (`metagate.bootstrap.md` §1: "fills in what the operator did not specify"). Every receipt that gate emits
  for the rest of its life goes to the attacker, and `metagate_bootstrap.py:195-201` logs a divergence only
  when a value *was* configured, so the silent case is the unmonitored one. Nothing in the receipt chain
  detects it: ReceiptGate is a leaf that never phones home to confirm it received anything.
- **BT-2 (HIGH) — the same spoof harvests credentials.** `_mcp_call` sends `X-API-Key: <the gate's real
  MetaGate key>` to the spoofed endpoint on line 124. One successful impersonation yields a valid credential
  for the genuine MetaGate for every gate that boots. There is no channel binding, no nonce, no
  `k8s/` NetworkPolicy restricting who may reach or impersonate port 8000.

**Fail-closed or fail-open on bootstrap failure?** Fail-open, deliberately, and this is spec-correct
(`metagate.bootstrap.md` §2: "Bootstrap must never prevent startup"; `metagate_bootstrap.py:221-229` catches
`Exception` and returns `BootstrapResult(succeeded=False)`). The implementation honours it. But combined with
BT-1 the property inverts into an attack aid: an attacker who takes the real MetaGate offline and answers in
its place is indistinguishable, to every gate, from a healthy MetaGate — because a gate that cannot verify
the packet also cannot verify the *speaker*. Fail-open without authentication of the responder is the
weakness, not fail-open itself.

**Minimum fix:** sign the Welcome Packet (detached signature over the canonical packet body with a key the
gates hold out-of-band, or mutual TLS with pinned MetaGate identity), and have `bootstrap_from_metagate`
refuse to *apply* an unverified packet while still not raising. Applying nothing preserves "never prevent
startup" and removes the silent-poisoning primitive.

## Credential Handling Audit

**Vendored-copy comparison (as requested).** Confirmed: the prior reviewer was right, and **upstream is the
good version**.

- `LegiVellum/.standalone_code/MetaGate/src/metagate/auth/auth.py:40-42` —
  `return hashlib.sha256(api_key.encode()).hexdigest()`: unsalted, uncosted, lookup-by-hash.
- `/home/claude/lv/MetaGate/src/metagate/auth/auth.py:52-59` — `bcrypt.hash(api_key)`.

Full delta beyond hashing: upstream adds `is_admin_principal` (auth.py:43-49) and `require_admin`
(auth.py:197-206) — both absent from the vendored copy, which pairs with that copy's unauthenticated
`api/admin.py`. The vendored tree is the pre-MCP REST layout (`src/metagate/api/{admin,bootstrap,
discovery,startup}.py`) with no `tests/`, no `mcp/`, no `tenancy.py`, no `api_keys.py`. It is a stale
January snapshot and should be deleted or clearly marked, not diffed against for guidance.

**Entropy — good.** `api_keys.py:47-49`: `f"mgk_{secrets.token_urlsafe(32)}"`, 256 bits from a CSPRNG,
prefixed for greppability. `api_keys.py:112-135` returns plaintext exactly once and persists only the hash;
`_serialize` (api_keys.py:52-65) never includes key material even truncated. This is the strongest part of
the repo and is well tested (`test_api_key_issuance.py`, 16 cases).

**Storage/comparison — three defects:**

- **CH-1 (HIGH) — full-table bcrypt scan per request.**
  ```python
  # src/metagate/auth/auth.py:106-127
  result = await db.execute(select(ApiKey).where(ApiKey.status == "active"))
  api_key_records = result.scalars().all()
  ...
  for record in api_key_records:
      if _is_bcrypt_hash(record.key_hash):
          if bcrypt.verify(api_key, record.key_hash):
  ```
  bcrypt is deliberately ~250 ms at default cost. Failure scenario: a stack with 20 active keys, an
  unauthenticated attacker POSTs `{"method":"tools/call","params":{"name":"metagate.bootstrap"}}` with a
  junk `X-API-Key`. No record matches, so all 20 verifications run: ~5 s of CPU per request, single-threaded
  in the event loop. The rate limiter allows 100/min/IP (`rate_limit.py:50-52`) — one IP at the limit
  consumes ~8 CPU-minutes per wall minute. MetaGate is the service the entire fleet must reach at startup;
  pegging it stalls every cold start. This is also a plain scalability wall: auth latency grows linearly
  with the number of issued keys, forever. Fix: store a fast lookup discriminator (HMAC-SHA256 of the key
  under a server pepper, indexed and unique) and bcrypt-verify exactly the one candidate row.
- **CH-2 (HIGH) — unsalted SHA-256 is still accepted, and the repo's own seeding path still writes it.**
  auth.py:124 accepts a legacy `sha256` hash via `secrets.compare_digest` (constant-time — correct as far as
  it goes) and upgrades it in place on next use. But `scripts/seed_data.py:114` —
  `key_hash = hashlib.sha256(api_key.encode()).hexdigest()` — is the README-documented way to create the
  first key. Failure scenario: an operator follows README "Seed Test Data", the key lands as unsalted
  SHA-256; if that key is never used, or the row is dumped before first use, an attacker with a DB read
  recovers the key from a rainbow table. The bcrypt migration is undone by the repo's own tooling.
- **CH-3 (MEDIUM) — silent crypto downgrade on hashing failure.**
  ```python
  # src/metagate/auth/auth.py:52-59
  try:
      return bcrypt.hash(api_key)
  except Exception:
      if settings.debug:
          return hashlib.sha256(api_key.encode()).hexdigest()
      raise
  ```
  `passlib==1.7.4` pinned against an unpinned `bcrypt` backend (`requirements.txt:9`) is a known-fragile
  pairing. Under `METAGATE_DEBUG=true` — which `config.py:110-117` makes the *only* way to run with the
  default JWT secret, i.e. the usual dev posture — a backend failure silently reverts every newly issued key
  to unsalted SHA-256 with no log line. `test_auth.py:20-36` explicitly accepts either output, so the test
  suite ratifies the downgrade instead of catching it.

**Rotation/revocation — adequate.** `revoke_api_key` (api_keys.py:161-188) flips status rather than
deleting, preserving the trail; `verify_api_key` re-queries `status == "active"` per request, so revocation
propagates on the next call with no cache to invalidate. Expiry is enforced twice (auth.py:117 and 133).
Rotation is issue-new + revoke-old, which is fine for v1 but undocumented as a procedure.

**Admin-principal determination — weak but not broken.**
```python
# src/metagate/auth/auth.py:43-49
if principal.principal_type in settings.admin_principal_types:   # default ["admin"]
    return True
if principal.principal_key in settings.admin_principal_keys:
    return True
```
`principal_type` is free text supplied at creation (`schemas.py:103`) and stored unconstrained (no CHECK
constraint in `migrations/001_initial_schema.sql:8-17`). Admin-ness is therefore a string an admin types,
not a modelled role. No privilege-escalation path from a normal principal was found — creating principals
and minting keys both sit behind `is_admin_principal` (`routes.py:605-607`) — but the blast radius of one
compromised admin key is total and there is no separation between "operator who publishes topology" and
"admin who mints credentials", despite `metagate.bootstrap.md` §3 describing exactly that distinction
("A component-owner key is sufficient; publishing topology requires an operator key").

## Critical & High Findings

### C-1 (CRITICAL) — `docker-compose.yml` env vars are unprefixed; the stack cannot start
`docker-compose.yml:12-18` vs `src/metagate/config.py:12-18`
```yaml
# docker-compose.yml:12-15
- DATABASE_URL=postgresql+asyncpg://metagate:metagate@db:5432/metagate
- JWT_SECRET=${JWT_SECRET:-change-me-in-production}
- DEBUG=${DEBUG:-false}
```
```python
# src/metagate/config.py:12-18
model_config = SettingsConfigDict(env_prefix="METAGATE_", env_file=".env", ...)
```
Failure scenario: `./run_local.sh` → `docker compose up --build`. `METAGATE_JWT_SECRET` is unset, so
`jwt_secret` takes its default `"change-me-in-production"`; `METAGATE_DEBUG` is unset so `debug` is `False`;
`validate_jwt_secret` (config.py:110-117) raises `ValueError`. `Settings()` is constructed at import time
(`config.py:128-131` via `main.py:21`), so uvicorn dies before binding. The Dockerfile copies only `src/`
and `migrations/` (Dockerfile:27-28), so no `.env` rescues it. `.env.example` repeats the same unprefixed
names (`.env.example:5-27`). The README table (lines 110-167) has the *correct* prefixed names — docs and
compose contradict each other, and only the docs are right. Exit criteria §1 "cold start succeeds" fails at
the first command in the README.

### C-2 (CRITICAL) — the mounted migration lacks columns the ORM selects; authentication breaks on a fresh DB
`docker-compose.yml:41`, `migrations/001_initial_schema.sql` (0 occurrences of `created_by`),
`src/metagate/models/db_models.py:35-36,157`
```yaml
# docker-compose.yml:41  — only 001 is mounted; 002 is never applied
- ./migrations/001_initial_schema.sql:/docker-entrypoint-initdb.d/001_initial_schema.sql:ro
```
```python
# src/metagate/models/db_models.py:157
created_by = Column(Text, nullable=True)   # api_keys.created_by — added only by 002
```
Failure scenario: fresh volume, compose brings up Postgres with 001 only. Any request with an API key runs
`select(ApiKey)` (auth.py:106-108), SQLAlchemy emits `SELECT api_keys.created_by ...`, Postgres returns
`UndefinedColumn`. **Every authenticated call fails**, including `metagate.bootstrap` — the one thing the
rest of the stack needs. Same defect hits `principals`, `profiles`, `manifests`, `bindings`, `secret_refs`,
plus the `audit_log` table `db_models.py:162` maps. Invisible to CI because `conftest.py:47` builds the
schema with `Base.metadata.create_all` rather than running the SQL. Compounding: `k8s/postgresql-init-configmap.yaml`
embeds a *third*, hand-merged schema that does include these columns — so k8s and compose deploy different
databases from the same repo, and neither is derived from `migrations/`.

### H-1 (HIGH) — anyone authenticated can close anyone else's startup session, cross-tenant
`src/metagate/mcp/routes.py:566-588`, `src/metagate/services/startup.py:34-56`
```python
# routes.py:566-573 — no ownership or tenant check on startup_id
if name == "metagate.startup_ready":
    response = await mark_startup_ready(
        db=db, startup_id=UUID(arguments["startup_id"]), ...
```
```python
# startup.py:28-31 — lookup by id alone
result = await db.execute(select(StartupSession).where(StartupSession.id == startup_id))
```
`mark_startup_ready` / `mark_startup_failed` never compare `session.subject_principal_key` or
`session.tenant_key` against the authenticated principal. Attacker capability: any valid API key in any
tenant (the lowest-privilege credential the system issues), plus knowledge of a `startup_id`. Failure
scenario: a tenant-B component calls `metagate.startup_failed` with tenant-A's ReceiptGate `startup_id`;
MetaGate flips the session to FAILED, writes attacker-controlled text into `failure_payload`, and emits a
`complete`/`failure` receipt to ReceiptGate with `from_principal` and `for_principal` set to *the victim's*
principal key (`receipts.py:97-98`) and `outcome_text = f"startup_failed:{error}"` (startup.py:125). That is
receipt forgery laundered through the trust root: the canonical ledger records a failure attributed to a
component that is running fine. `startup_id` is a UUID4 so it is not guessable, but it is disclosed to the
component, appears in `metagate.bootstrap` responses, and is logged (`metagate_bootstrap.py:260`) — this is
a capability leak, not a secret. Fix: scope the lookup by the authenticated principal's tenant and require
`session.subject_principal_key == auth.principal.principal_key`.

### H-2 (HIGH) — `instantiate_problemata` reads and rebinds principals/profiles/manifests across tenants
`src/metagate/services/problemata.py:172-176`, `189-191`, `206-208`
```python
# problemata.py:172-176 — no tenant filter
principal = (
    await db.execute(
        select(Principal).where(Principal.principal_key == derived["principal_key"])
    )
).scalar_one_or_none()
```
`principal_key` is globally unique (`db_models.py:29`, `migrations/001_initial_schema.sql:11`), so this
lookup crosses tenants by construction. `routes.py:600` carefully resolves `tenant_key` through
`resolve_tenant_key`, which refuses cross-tenant requests when `admin_allow_cross_tenant` is false
(`tenancy.py:12-13) — and then `instantiate_problemata` ignores it. Attacker capability: admin in tenant A.
Failure scenario: tenant-A admin submits a Problemata whose `problemata.owner_principal` equals tenant-B's
`receiptgate` principal key, with `primitives` pointing at attacker-controlled endpoints. The tenant-B
principal is found and reused (not created), a tenant-A-owned profile/manifest is created, and a binding is
written joining tenant B's identity to tenant A's manifest (problemata.py:246-254). Tenant B's ReceiptGate
then bootstraps into the attacker's topology. `resolve_tenant_key`'s guarantee is a facade for this path.
Same missing filter on `profile_key` (189) and `manifest_key` (207), both also globally unique.

### H-3 (HIGH) — bootstrap blocks on a 10 s network call to ReceiptGate, violating the non-blocking invariant
`src/metagate/services/bootstrap.py:307-313`, `src/metagate/receiptgate_client.py:47`
```python
# bootstrap.py:307-313 — inside the request path, before the packet is returned
await emit_startup_receipt(session=startup_session, phase="accepted", ...)
```
```python
# receiptgate_client.py:47
async with httpx.AsyncClient(timeout=10.0) as client:
```
Spec §2 (hard invariant): request handling must be "synchronous, bounded, **DB-only**, side-effect minimal…
MetaGate may fail fast, but must not wait." §12: "MetaGate must never block on other services." Failure
scenario — the thundering herd this repo is most exposed to: the stack restarts, nine gates call
`metagate.bootstrap` within a second, ReceiptGate is still starting and its socket accepts but does not
respond. Each bootstrap holds a pooled DB session (`routes.py:544`) for the full 10 s. Pool is
10 + 20 overflow (`database.py:26-28`); at ~30 concurrent slow bootstraps the pool is exhausted and *new*
requests, including `metagate.health` — no, health short-circuits, but every admin and bootstrap call —
queue behind it. Meanwhile each gate's own 5 s client timeout (`metagate_bootstrap.py:168`) has already
fired, so they gave up, will retry, and MetaGate is still holding connections for answers nobody is waiting
for. Fix: enqueue the receipt (outbox row) and emit out-of-band, or fire-and-forget with a ~1 s timeout.

### H-4 (HIGH) — startup receipts are addressed to two different inboxes; the obligation never closes
`src/metagate/services/receipts.py:56`, `94`, `97-98`
```python
# receipts.py:56
recipient_ai = session.component_key if is_accepted else session.subject_principal_key
```
`receipt.rules.md` §7 defines the inbox as `recipient_ai = ? AND phase = 'accepted'`, and §1.2 requires the
`complete` receipt to resolve the obligation created by the `accepted` receipt *for the same task_id*.
Failure scenario: bootstrap opens the obligation addressed to `"receiptgate"` (a component name, not a
principal); `startup_ready` closes it addressed to `"receiptgate-main-principal"`. Any inbox query for
either identity sees half the pair — the component's inbox shows a permanently open obligation, the
principal's inbox shows a `complete` with no matching `accepted`. Compounding, on the same lines:
`caused_by_receipt_id` is hard-coded `"NA"` (receipts.py:94) for both phases, so the causality chain
required by core invariant 4 does not exist (the `accepted` receipt's id is never persisted, so it *cannot*
be referenced); and `from_principal`/`for_principal` (97-98) name the component for what is an
internal-origin MetaGate obligation, where the exit criteria require `SYSTEM_PRINCIPAL_ID` with
`svc:metagate` as emitter. No `SYSTEM_PRINCIPAL_ID`, `SERVICE_PRINCIPAL_ID`, or `TERMINAL_RECEIPT_TYPES`
constant exists in the repo.

### H-5 (HIGH) — see CH-1: unauthenticated CPU exhaustion via per-request bcrypt table scan
`src/metagate/auth/auth.py:106-127`. Detailed in the Credential Handling section.

## Medium Findings

### M-1 — `services/audit.py` is dead code; no admin mutation is audited
`src/metagate/services/audit.py` (186 lines), zero external callers (verified by grep for
`record_audit|audit_create|audit_update|audit_delete` across the repo — only self-references inside the
module). `migrations/002_audit_logging.sql:28-41` creates the table; `db_models.py:162-181` maps it; nothing
writes a row. Failure scenario: an admin key is compromised and used to repoint every manifest's
`receiptgate` endpoint via `metagate.admin_manifests`. Post-incident there is no record of who did it or
when — only the mutated rows. README (line 98) and `002`'s `COMMENT ON TABLE ... 'Immutable audit trail'`
both advertise a capability that does not exist. This is CODE_REVIEW_1's MED-SEC-002 half-fixed: the schema
landed, the wiring did not.

### M-2 — the "exactly one active binding" invariant is enforced only in SQL, and the code violates it
`src/metagate/services/problemata.py:245-256`, `migrations/001_initial_schema.sql:72`,
`src/metagate/mcp/routes.py:399-406`
```sql
-- migrations/001_initial_schema.sql:72
CREATE UNIQUE INDEX idx_bindings_principal_active ON bindings(principal_id) WHERE active = true;
```
```python
# problemata.py:246-254 — creates a second active binding without deactivating the first
binding = Binding(..., active=True)
db.add(binding)
```
Failure scenario: re-instantiate the same Problemata at version 0.2.0. `derive_topology` scopes keys by
version (`problemata.py:87`), so new `profile_key`/`manifest_key` ⇒ new rows ⇒ new binding for the *same*
`owner_principal`, whose 0.1.0 binding is still `active = true`. Postgres raises
`UniqueViolation` on `idx_bindings_principal_active`; `routes.py:644` renders it as a JSON-RPC error string
containing the SQL and index name. **Topology upgrade is impossible** — the only recovery is manual SQL.
Invisible in tests because the partial index is not declared on the ORM model (`db_models.py:82-100`), so
`create_all` never builds it and `conftest.py` happily creates overlapping active bindings
(`test_bootstrap.py:111-120` does exactly that). `_handle_admin_bindings` create (routes.py:399-406) has the
identical defect. Related latent bug if the index is ever dropped: `get_active_binding`
(`bootstrap.py:98-104`) uses `.limit(1)` with **no ORDER BY**, so which manifest a gate receives becomes
non-deterministic — a silent config-poisoning primitive.

### M-3 — OPEN startup sessions are never reclaimed
`src/metagate/services/bootstrap.py:169-184`
```python
delete(StartupSession).where(
    StartupSession.created_at < cutoff,
    StartupSession.status.in_(["READY", "FAILED"])
)
```
Failure scenario: a gate crash-loops (bad config, OOM). Each restart calls `metagate.bootstrap`, each
bootstrap inserts an OPEN row (`bootstrap.py:302`), and no acknowledgement ever arrives. The retention job
only deletes terminal rows, so OPEN rows accumulate without bound — a restart loop at 6 restarts/min adds
~250k rows/month. Spec §11 ("cleanup allowed only after mirror or explicit skip") is also violated in the
other direction: the job deletes rows regardless of `mirror_status`, which is set to `"PENDING"` at creation
(`bootstrap.py:158`) and never updated anywhere, so every session is deleted un-mirrored. Spec §10 mirroring
is a schema-only stub with no in-repo statement that it is deferred.

### M-4 — error envelopes leak internal detail and drop the spec's status codes
`src/metagate/mcp/routes.py:644-645`, `557-560`
```python
except Exception as exc:
    return _jsonrpc_error(request_body.id, getattr(exc, "code", "ERROR"), str(exc))
```
Failure scenario: `metagate.admin_principals` create with a duplicate `principal_key` raises
`IntegrityError`; `str(exc)` is returned verbatim to the caller, including the SQL statement, the index name
and the bound parameters. Conversely, `routes.py:557-560` rewraps `BootstrapError`/`ForbiddenKeyError` as
plain `ValueError(exc.message)`, discarding the `.code` and `.status_code` those classes carry — so every
error emerges as code `"ERROR"` over HTTP 200, and spec §3's "Failure → 403 / 409 (never partial success)"
is unobservable on the wire. CODE_REVIEW_1's HIGH-SEC-002 was fixed for the FastAPI handler
(`main.py:153` gates on debug) but reintroduced on the MCP path, which is now the only path.

### M-5 — rate limiting is per-process, per-IP, and double-counted
`src/metagate/middleware/rate_limit.py:50-52`, `src/metagate/main.py:159`, `src/metagate/mcp/routes.py:627`
```python
client_ip = request.client.host if request.client else "unknown"
key = f"ip:{client_ip}"
```
Three problems. (a) `main.py:159` attaches `rate_limit_dependency` to the router *and* `mcp_entry` calls
`await _rate_limit(request)` at line 627 — every request consumes two tokens, so the effective limit is 50/min,
not the documented 100. (b) State is a process-local dict, while `k8s/deployment.yaml:10` runs 2 replicas
and `k8s/hpa.yaml:15` scales to 10 — the real limit is 100 × replicas, and it resets on every scale event.
(c) Keying on `request.client.host` behind a k8s Service or ingress collapses the entire fleet onto one
bucket: nine gates restarting together can rate-limit each other out of bootstrap, while a distributed
attacker gets a fresh bucket per source IP. `extract_request_info` (`audit.py:95-97`) already knows about
`X-Forwarded-For`; the limiter does not.

### M-6 — unbounded input on every write path
`src/metagate/mcp/routes.py:48` (`params: dict[str, Any]`), `models/schemas.py:124-152`
(`capabilities`/`policy`/`services`/`memory_map`/`polling`/`schemas`: bare `dict[str, Any]`),
`problemata.py:92` (unbounded iteration over caller-supplied `primitives`). No length, depth, or byte cap
anywhere; `check_forbidden_keys` recurses without a depth limit (`bootstrap.py:45-69`), so a deeply nested
spec is a stack-overflow candidate before it is a storage problem. `receipt.rules.md` §8 recommends explicit
size caps; none are enforced. CODE_REVIEW_1 MED-SEC-001, still open.

### M-7 — `component_key` authorization is effectively off for Problemata-derived profiles
`src/metagate/services/bootstrap.py:224-230` vs `src/metagate/services/problemata.py:125`
```python
# bootstrap.py:224 — reads capabilities["allowed_components"]
allowed_components = profile.capabilities.get("allowed_components", [])
```
```python
# problemata.py:125 — writes capabilities["allowed"]
"capabilities": {"allowed": sorted(capabilities)},
```
Key mismatch: `allowed` vs `allowed_components`. Failure scenario: every profile created by
`metagate.instantiate_problemata` — i.e. every profile in the intended production path — has no
`allowed_components`, so the check short-circuits and any authenticated principal bootstraps under any
`component_key` it likes. The `component_key` then lands unvalidated in the startup session
(`bootstrap.py:151`) and in the receipt's `recipient_ai` (`receipts.py:56`), letting a component post
lifecycle receipts into another component's inbox. Spec §3 requires "component_key is permitted by binding".
CODE_REVIEW_1's CRIT-004 fix works only for hand-written profiles, which the tests exclusively use
(`conftest.py:122`).

### M-8 — `requirements.txt` / `pyproject.toml` drift, and the container ships the wrong set
`requirements.txt:1-12` vs `pyproject.toml:20-34`. `pyproject` lists `aiosqlite>=0.19.0` as a runtime
dependency; `requirements.txt` omits it, and the Dockerfile installs only `requirements.txt`
(Dockerfile:21-24). Failure scenario: run the container in the debug/sqlite mode that `config.py:96`
explicitly supports → `ModuleNotFoundError: aiosqlite`. `requirements.txt` pins `==`, `pyproject` floors
`>=`; CI installs both in sequence (`.github/workflows/ci.yml:31-32`), so the pins silently downgrade
whatever pyproject resolved and CI tests a third dependency set that neither file alone describes.
`passlib[bcrypt]==1.7.4` leaves the `bcrypt` backend unpinned — the exact fragility CH-3 papers over.

## Low / Nits

- **L-1** — `bootstrap.py:75`: MD5 for the ETag. Not security-relevant here, but it will trip FIPS-mode
  interpreters (`hashlib.md5` raises without `usedforsecurity=False`) and any supply-chain scanner.
  CODE_REVIEW_1 LOW-001, still open. One-line fix to `sha256(...).hexdigest()[:32]`.
- **L-2** — `k8s/configmap.yaml:17` sets `METAGATE_VERSION: "0.1"`, but the field is `metagate_version`
  under prefix `METAGATE_`, so the real variable is `METAGATE_METAGATE_VERSION` (README:114 documents this
  correctly). The k8s value is silently discarded by `extra="ignore"` (config.py:17).
- **L-3** — `config.py:81` omits `X-API-Key` from `cors_allowed_headers` while `api_key_header` defaults to
  `X-API-Key` (config.py:36). A browser client cannot send the credential the service expects. Not
  exploitable, just incoherent.
- **L-4** — `main.py:130-131`: `x-trace-id` is taken from an untrusted header and echoed into every
  structlog event (`logging.py:34-41`) and back in the response, with no length or charset validation —
  log-injection / log-bloat vector.
- **L-5** — `docker-compose.yml:42-43` publishes Postgres on host `5432` with `metagate:metagate`
  (lines 36-37). CODE_REVIEW_1 LOW-002/LOW-003, still open. `k8s/secret.yaml:16,20,35` ships `CHANGE_ME`
  placeholders — no real secrets committed (good), but also no ExternalSecret/SealedSecret path documented.
- **L-6** — `problemata.py:156-168` runs the forbidden-key check *before* the validation-attestation check,
  so an unvalidated spec containing `deploy` returns `FORBIDDEN_KEYS` rather than `PROBLEMATA_UNVALIDATED`.
  Cosmetic, but it misleads the operator about why the spec was refused.
- **L-7** — `routes.py:629-630`: `tools/list` is unauthenticated and enumerates the full admin surface. Low
  value to an attacker, free to gate.
- **NIT** — `k8s/` has no NetworkPolicy. For the component whose impersonation compromises the whole mesh
  (BT-1), "any pod in the cluster may reach and may claim to be MetaGate" is the wrong default.
- **NIT** — `.coverage` is committed at the repo root.
- **SUSPECTED** — `passlib 1.7.4` + `bcrypt >= 4.1` is widely reported to break passlib's backend version
  probe. I could not confirm the runtime behaviour here (no packages installed, per the review rules).
  To check: `pip install -r requirements.txt && python -c "from passlib.hash import bcrypt; bcrypt.hash('x')"`
  and confirm it returns `$2b$...` rather than raising. If it raises, CH-3 fires on every key issued in debug.

## Spec drift vs `metagate.bootstrap.md`

| Spec says | Code does |
|---|---|
| §2 "Bootstrap must never prevent startup… every failure degrades to a logged warning" | Honoured. `metagate_bootstrap.py:221-229` catches `Exception`, returns `succeeded=False`. |
| §2 "Explicit configuration wins… divergence is logged rather than silently resolved" | Honoured for the *configured* case (`metagate_bootstrap.py:195-201`), but the unset case — the common one — applies the mesh value with only an aggregate `applied=` log line. No integrity check makes "the mesh" trustworthy (BT-1). |
| §3 `<PREFIX>METAGATE_COMPONENT_KEY` default: "the gate's own name" | `metagate_bootstrap.py:162-166` falls back to the literal string `"component"` when neither the argument nor the setting is present. A gate that forgets the setting bootstraps as `"component"`, and MetaGate accepts it (M-7). |
| §3 `<PREFIX>METAGATE_BOOTSTRAP_TIMEOUT_SECONDS` default `5.0`, "a slow MetaGate must not become a slow startup" | Honoured client-side (`metagate_bootstrap.py:168`). Server-side MetaGate can still take 10 s per bootstrap (H-3), so the client times out and retries against a server still working on the abandoned request. |
| §3 "A component-owner key is sufficient; publishing topology requires an operator key" | No such distinction exists. `is_admin_principal` (auth.py:43-49) is a single boolean; there is no operator role, and any admin can both publish topology and mint credentials. |
| §5 "`metagate.startup_failed` — when the gate cannot start" | The shared client implements only `startup_ready` (`metagate_bootstrap.py:232-266`). Nothing ever calls `startup_failed`, so a gate that dies after bootstrap leaves an OPEN session forever (M-3). |
| §5 "`build_version` … always sent, defaulting to `0.1.0`" | Honoured (`metagate_bootstrap.py:247, 257`). |
| §5 "MetaGate records which build is running where" | Recorded in `ready_payload` (startup.py:61-65), then deleted by retention after 72 h (bootstrap.py:169-184) with no aggregate view. `metagate.startup_ready` has no ownership check, so the record is attacker-writable (H-1). |
| §6 "Gates load it from a sibling LegiVellum checkout rather than vendoring it" | MetaGate itself vendors nothing but does a `sys.path.append` walk up the tree to find `LegiVellum/shared` (`receipts.py:16-28`); if not found, receipts skip canonical validation and are emitted unvalidated (`receipts.py:137-138`). Degradation is silent — no warning on the import-failure branch. |
| MetaGate spec §11 "Cleanup allowed only after mirror or explicit skip" | `cleanup_old_sessions` ignores `mirror_status` entirely (bootstrap.py:178-181); `mirror_status` is never advanced past `"PENDING"` anywhere in the codebase. |
| MetaGate spec §12 "Every bootstrap creates exactly one OPEN startup receipt" | An ETag hit returns `{"not_modified": True}` and creates no session (bootstrap.py:297-298, routes.py:562-563). Unreached today only because the shared client never sends `last_packet_etag`. |

## Test Coverage Gaps

8 files, ~1.1k lines. Genuinely good: forbidden-key recursion including lists
(`test_problemata_instantiation.py:186`), Problemata derivation determinism and idempotent key scoping,
and the 16-case API-key issuance/revocation suite. `test_auth.py:20-36` does test hashing — but is written
to accept the SHA-256 fallback, so it cannot fail on CH-3.

Bootstrap auth **is not** tested at the level that matters: `test_admin.py:9-24` and `:64-83` verify that
*unauthenticated* calls are rejected. Nothing verifies that an *authenticated non-admin* is rejected — the
`is_admin_principal` branch at `routes.py:605-607` has no negative-path test, and `test_auth.py:89-107`
tests the predicate in isolation, not its enforcement.

Missing regressions, in priority order:

1. **Authenticated non-admin is refused every `metagate.admin_*` tool and `instantiate_problemata`.** The
   single highest-value missing test; the whole topology-write authz story rests on one uncovered branch.
2. **`startup_ready`/`startup_failed` from a principal that does not own the session is refused** (H-1).
   Currently the behaviour under test would be "succeeds", which is the bug.
3. **`instantiate_problemata` cannot touch a principal/profile/manifest in another tenant** (H-2).
4. **Re-instantiating a Problemata at a new version succeeds** (M-2) — must run against Postgres with
   `migrations/001` applied, not `create_all`, or the partial unique index is absent and the test is
   vacuous.
5. **Migrations apply cleanly to an empty Postgres and the ORM round-trips every model** (C-2). A
   `create_all`-only suite structurally cannot catch schema drift; one `testcontainers`-style Postgres test
   would have caught both C-2 and M-2.
6. **`build_startup_receipt` output validates against `receipt.schema.v1.json` for both phases, and the
   `complete` receipt's `recipient_ai` equals the `accepted` receipt's** (H-4). `receipts.py` has zero
   direct test coverage today.
7. **Bootstrap returns within a bounded time when ReceiptGate is unreachable/hanging** (H-3).
8. **`hash_api_key` never returns a non-bcrypt hash**, unconditionally — replacing the current
   debug-tolerant assertion (CH-3).
9. **A profile created by `instantiate_problemata` still enforces `component_key`** (M-7) — the key-name
   mismatch survives precisely because every test uses hand-built profiles.

`.github/workflows/ci.yml:51` sets `--cov-fail-under=60`, which for a trust root is low; the uncovered 40%
is where H-1, H-2 and M-7 live.

## Delta vs CODE_REVIEW_1.md

CODE_REVIEW_1 is explicitly marked legacy (2026-01-08, pre-MCP). Tracking its findings forward:

**Fixed:**
- CRIT-001 admin endpoints unauthenticated → fixed; `routes.py:605-607` gates all `admin_*` tools, and
  `instantiate_problemata` is gated too with a comment explaining why (`routes.py:590-595`).
- CRIT-002 `allow_origins=["*"]` → fixed; explicit allowlist in `config.py:68-71`.
- CRIT-003 default JWT secret → fixed; `config.py:110-117` refuses the default outside debug. (This is also
  what makes C-1 a hard crash rather than an insecure boot — arguably working as intended.)
- HIGH-001 no tests → fixed; 8 files exist, with real assertions.
- HIGH-002 unsalted SHA-256 → fixed **upstream** (auth.py:52-59), and the vendored copy is confirmed stale.
  Partially undone by CH-2 (`seed_data.py:114` still writes SHA-256, and the verifier still accepts it).
- HIGH-004 no rate limiting → fixed in substance (`middleware/rate_limit.py`), with new defects (M-5).
- HIGH-005 retention not implemented → fixed (`main.py:37-54`, `bootstrap.py:169-184`), incompletely (M-3).
- MED-001 no structured logging → fixed; `logging.py` + trace-id middleware.
- MED-003 API key rotation/revocation → fixed; `services/api_keys.py` is new and well built.
- LOW-002 `== True` → fixed; `bootstrap.py:101` uses `.is_(True)`.
- MED-005 missing README → fixed; README is thorough and mostly accurate (the config table is *more*
  correct than compose).

**Still open:**
- CRIT-004 component_key not validated → fixed for hand-written profiles, **regressed in effect** for
  Problemata-derived ones (M-7).
- HIGH-003 error detail leakage → fixed on the FastAPI handler, reintroduced on the MCP path (M-4).
- MED-SEC-001 no JSONB size limits → open (M-6).
- MED-SEC-002 no audit logging → half-fixed: table + service exist, nothing calls them (M-1).
- Mirror status never updated (spec §10) → open, unchanged.
- "Single active binding not enforced" → SQL index exists but the ORM does not know about it and the code
  violates it (M-2). Arguably worse than in January, because `instantiate_problemata` now trips it.
- Alembic recommended → open; alembic is still a dependency with no migration environment.

**Regressed / newly introduced since:**
- C-1 (compose env prefix) — `env_prefix="METAGATE_"` was introduced with the settings rework; compose was
  never updated. The stack ran in January and does not now.
- C-2 (migration 002 not mounted, ORM/SQL drift) — 002 was added 2026-01-09 and never wired into compose.
- H-1 (startup ack ownership) — the January REST `api/startup.py` had the same gap; carried forward
  unchanged into the MCP rewrite.
- H-2, H-3, H-4 — all in code written after the January review (`problemata.py`, `receipts.py`,
  `receiptgate_client.py`), none of it reviewed since.

## Cross-repo observations

- **The shared bootstrap client is the right call and the right place for the fix.** `metagate_bootstrap.py`
  is well-written — the `_same_endpoint` canonicalization (lines 74-90) and the tolerant
  `endpoint_for_type` (93-110) both show scar tissue from real incidents. Because it is shared, packet
  verification can be added in *one* file and every gate gets it. Do that rather than adding signing to
  MetaGate alone.
- **`LegiVellum/.standalone_code/MetaGate/` is a hazard.** It contains unsalted SHA-256 key hashing and
  unauthenticated admin CRUD, in a tree that reads like current source. Anyone grepping the monorepo for
  `hash_api_key` finds the bad one first. Delete it or add a prominent `STALE_SNAPSHOT.md`.
- **The `component_key` vocabulary is unowned.** `metagate.bootstrap.md` §4 says component keys default to
  "the gate's own name"; the client defaults to `"component"`; MetaGate validates against
  `capabilities["allowed_components"]` while its own Problemata path writes `capabilities["allowed"]`. Three
  repos, three conventions. Pick one and put it in the canonical doc as a normative list.
- **Receipt principal conventions are absent here but present in the exit criteria**, which suggests other
  gates may define `SYSTEM_PRINCIPAL_ID`/`SERVICE_PRINCIPAL_ID` locally. If so, MetaGate's startup receipts
  will not join the same causality graph as everyone else's — worth a cross-repo grep before any gate tags
  v1.
- **ReceiptGate is the only consumer of MetaGate's receipts and cannot detect their absence.** With
  emission best-effort (`receiptgate_client.py:55-57` swallows everything) and `mirror_status` never
  advanced, a silently dropped startup receipt is unrecoverable and invisible from both ends.

## What's solid

- `services/api_keys.py` — issuance/revocation is genuinely well designed: CSPRNG entropy, plaintext
  returned once, hash-only persistence, revoke-by-status for the audit trail, tenant checks on both issue
  and revoke, and 16 tests covering it.
- `check_forbidden_keys` (`bootstrap.py:45-69`) descends lists as well as dicts, with a comment explaining
  the Problemata edge-list case that motivated it — and a test for exactly that
  (`test_problemata_instantiation.py:186`).
- `derive_topology` (`problemata.py:62-132`) is a pure function with derived, collision-free keys, tested
  without a database. The right factoring.
- The describe-only boundary is enforced, not just documented: `instantiate_problemata` refuses
  unvalidated specs (problemata.py:163-168) and applies the forbidden-key check to incoming specs.
- No SQL injection anywhere — everything goes through the SQLAlchemy expression API, and `seed_data.py`
  uses asyncpg parameter binding.
- No SSRF: caller-supplied endpoints are stored as world-truth and never fetched; the only outbound call
  targets a config-supplied endpoint validated for scheme (`config.py:119-125`).
- `logging.py` + trace-id middleware, and the pervasive explanatory module docstrings (`api_keys.py:1-19`,
  `problemata.py:1-22`) — these explain *why*, which is rare and made this review much faster.
