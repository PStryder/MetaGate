"""Materialize a validated Problemata spec as MetaGate world-truth.

This closes the gap between the LegiVellum control plane, which authors and
validates Problemata specs, and MetaGate, which components bootstrap against.
Before this, the two halves never touched: the demo stack seeded MetaGate by
raw SQL INSERTs, so a Problemata spec described a topology nothing could
actually boot into.

Authority boundaries this respects
----------------------------------
MetaGate is a describe-only bootstrap authority. "Instantiate" here means
*materialize as world-truth* -- register principal, profile, manifest and
binding so components can bootstrap into the topology. It explicitly does not
mean deploy, provision, scale, or execute; the existing forbidden-key check is
applied to the incoming spec to keep that boundary enforced rather than merely
documented.

MetaGate also does not validate Problemata specs -- that is the platform's
responsibility (see docs/canonical/ alignment notes). It does, however, refuse
to materialize a spec that carries no passing validation attestation. Trusting
the validator is not the same as accepting anything.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import Binding, Manifest, Principal, Profile
from .bootstrap import BootstrapError, check_forbidden_keys

# Capabilities implied by each primitive type. A profile's capabilities describe
# what the bound principal may do, derived from the topology it participates in.
CAPABILITIES_BY_TYPE: dict[str, list[str]] = {
    "receiptgate": ["receipts.submit", "receipts.read"],
    "depotgate": ["artifacts.stage", "artifacts.read"],
    "asyncgate": ["tasks.lease", "tasks.complete"],
    "memorygate": ["memory.read", "memory.write"],
    "metagate": ["bootstrap.read"],
    "interrogate": ["admission.query"],
    "interview": ["observe.read"],
    "cognigate": ["cognition.execute"],
}


class ProblemataInstantiationError(BootstrapError):
    """Raised when a spec cannot be materialized."""

    def __init__(self, message: str, code: str = "PROBLEMATA_INVALID") -> None:
        super().__init__(message, status_code=400, code=code)


def _require(spec: dict[str, Any], key: str) -> Any:
    if key not in spec:
        raise ProblemataInstantiationError(f"Problemata spec is missing '{key}'")
    return spec[key]


def derive_topology(
    spec: dict[str, Any],
    *,
    tenant_key: str,
    deployment_key: str,
) -> dict[str, Any]:
    """Derive MetaGate records from a compiled Problemata spec.

    Pure: performs no I/O, so the mapping can be tested without a database.
    """
    problemata = _require(spec, "problemata")
    primitives = _require(spec, "primitives")
    if not isinstance(primitives, dict) or not primitives:
        raise ProblemataInstantiationError("Problemata spec declares no primitives")

    problemata_id = problemata.get("id")
    version = str(problemata.get("version") or "0.1.0")
    owner_principal = problemata.get("owner_principal")
    if not problemata_id:
        raise ProblemataInstantiationError("Problemata spec is missing problemata.id")
    if not owner_principal:
        raise ProblemataInstantiationError("Problemata spec is missing problemata.owner_principal")

    # Keys are derived, not supplied, so re-registering the same spec version is
    # idempotent and two problemata can never collide on one another's records.
    scope = f"problemata:{problemata_id}:{version}"

    services: dict[str, Any] = {}
    capabilities: set[str] = set()
    memory_map: dict[str, Any] = {}
    for ref, primitive in primitives.items():
        if not isinstance(primitive, dict):
            raise ProblemataInstantiationError(f"Primitive '{ref}' is not an object")
        ptype = primitive.get("type") or "unknown"
        services[ref] = {
            "type": ptype,
            "endpoint": primitive.get("endpoint"),
            "config": primitive.get("config") or {},
        }
        capabilities.update(CAPABILITIES_BY_TYPE.get(ptype, []))
        if ptype == "memorygate":
            memory_map[ref] = {"endpoint": primitive.get("endpoint")}

    defaults = problemata.get("defaults") or {}
    environment = {
        "problemata_id": problemata_id,
        "problemata_version": version,
        "trust_domain": defaults.get("trust_domain", "default"),
        "defaults": defaults,
        "labels": problemata.get("labels") or {},
        # Edges are world-truth about who may talk to whom, so components can
        # see the shape of the mesh they were bootstrapped into.
        "topology": spec.get("topology") or [],
    }

    return {
        "problemata_id": problemata_id,
        "version": version,
        "principal_key": owner_principal,
        "profile_key": f"{scope}:profile",
        "manifest_key": f"{scope}:manifest",
        "tenant_key": tenant_key,
        "deployment_key": deployment_key,
        "capabilities": {"allowed": sorted(capabilities)},
        "policy": spec.get("policies") or {},
        "environment": environment,
        "services": services,
        "memory_map": memory_map,
        "polling": {"bootstrap_interval_seconds": 300},
        "schemas": {"problemata_spec_version": version},
    }


def _validation_passed(validation: Optional[dict[str, Any]]) -> bool:
    if not isinstance(validation, dict):
        return False
    return str(validation.get("status", "")).lower() == "passed"


async def instantiate_problemata(
    db: AsyncSession,
    *,
    spec: dict[str, Any],
    validation: Optional[dict[str, Any]],
    tenant_key: str,
    deployment_key: str = "default",
    auth_subject: Optional[str] = None,
) -> dict[str, Any]:
    """Materialize a validated Problemata spec, idempotently."""
    if not isinstance(spec, dict):
        raise ProblemataInstantiationError("Problemata spec must be an object")

    # Describe-only boundary: a spec carrying task/deploy/execute keys is trying
    # to make MetaGate an orchestrator.
    forbidden = check_forbidden_keys(spec)
    if forbidden:
        raise ProblemataInstantiationError(
            f"Problemata spec contains forbidden keys: {sorted(forbidden)}",
            code="FORBIDDEN_KEYS",
        )

    if not _validation_passed(validation):
        raise ProblemataInstantiationError(
            "Problemata spec must carry a passing validation attestation; "
            "MetaGate does not validate specs itself.",
            code="PROBLEMATA_UNVALIDATED",
        )

    derived = derive_topology(spec, tenant_key=tenant_key, deployment_key=deployment_key)

    principal = (
        await db.execute(
            select(Principal).where(Principal.principal_key == derived["principal_key"])
        )
    ).scalar_one_or_none()
    if principal is None:
        principal = Principal(
            id=uuid4(),
            tenant_key=tenant_key,
            principal_key=derived["principal_key"],
            auth_subject=auth_subject or derived["principal_key"],
            principal_type="service",
            status="active",
        )
        db.add(principal)
        await db.flush()

    profile = (
        await db.execute(select(Profile).where(Profile.profile_key == derived["profile_key"]))
    ).scalar_one_or_none()
    if profile is None:
        profile = Profile(
            id=uuid4(),
            tenant_key=tenant_key,
            profile_key=derived["profile_key"],
            capabilities=derived["capabilities"],
            policy=derived["policy"],
        )
        db.add(profile)
        await db.flush()
    else:
        profile.capabilities = derived["capabilities"]
        profile.policy = derived["policy"]

    manifest = (
        await db.execute(select(Manifest).where(Manifest.manifest_key == derived["manifest_key"]))
    ).scalar_one_or_none()
    if manifest is None:
        manifest = Manifest(
            id=uuid4(),
            tenant_key=tenant_key,
            manifest_key=derived["manifest_key"],
            deployment_key=deployment_key,
            environment=derived["environment"],
            services=derived["services"],
            memory_map=derived["memory_map"],
            polling=derived["polling"],
            schemas=derived["schemas"],
            # manifests.version is a NOT NULL integer revision of the record,
            # distinct from the Problemata's semantic version (already encoded
            # in manifest_key). Left unset, SQLAlchemy sends an explicit NULL.
            version=1,
        )
        db.add(manifest)
        await db.flush()
    else:
        manifest.deployment_key = deployment_key
        manifest.environment = derived["environment"]
        manifest.services = derived["services"]
        manifest.memory_map = derived["memory_map"]
        manifest.polling = derived["polling"]
        manifest.schemas = derived["schemas"]

    binding = (
        await db.execute(
            select(Binding).where(
                Binding.principal_id == principal.id,
                Binding.profile_id == profile.id,
                Binding.manifest_id == manifest.id,
            )
        )
    ).scalar_one_or_none()
    created_binding = binding is None
    if binding is None:
        binding = Binding(
            id=uuid4(),
            tenant_key=tenant_key,
            principal_id=principal.id,
            profile_id=profile.id,
            manifest_id=manifest.id,
            active=True,
        )
        db.add(binding)
    else:
        binding.active = True

    await db.commit()

    return {
        "problemata_id": derived["problemata_id"],
        "version": derived["version"],
        "tenant_key": tenant_key,
        "deployment_key": deployment_key,
        "principal_key": principal.principal_key,
        "profile_key": profile.profile_key,
        "manifest_key": manifest.manifest_key,
        "binding_id": str(binding.id),
        "binding_created": created_binding,
        "services": sorted(derived["services"]),
        "capabilities": derived["capabilities"]["allowed"],
    }
