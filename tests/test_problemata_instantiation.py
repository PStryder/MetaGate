"""Tests for materializing a Problemata spec as MetaGate world-truth.

derive_topology is pure, so the spec -> records mapping and the authority
boundaries around it are testable without a database.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from metagate.services.problemata import (
    ProblemataInstantiationError,
    derive_topology,
    _validation_passed,
)


def _spec() -> dict[str, Any]:
    """A minimal spec shaped like legivellum.compile_problemata_blueprint output."""
    return {
        "problemata": {
            "id": "demo-curation",
            "version": "0.1.0",
            "tenant_id": "default",
            "owner_principal": "principal-demo",
            "labels": {"mode": "blueprint"},
            "defaults": {"trust_domain": "default", "receiptgate_ref": "receiptgate-main"},
        },
        "primitives": {
            "receiptgate-main": {
                "type": "receiptgate",
                "endpoint": "http://receiptgate:8000/mcp",
                "config": {"receipt_schema_version": "1.0"},
            },
            "asyncgate-main": {
                "type": "asyncgate",
                "endpoint": "http://asyncgate:8080/mcp",
                "config": {"lease_ttl_seconds": 300},
            },
            "memorygate-main": {
                "type": "memorygate",
                "endpoint": "http://memorygate:8000/mcp",
                "config": {},
            },
        },
        "topology": [
            {"from": "asyncgate-main", "to": "receiptgate-main", "purpose": "receipts"},
        ],
        "policies": {"trust_domain": "default", "rate_limits": {"global_requests_per_minute": 300}},
    }


def _derive(spec: dict[str, Any]) -> dict[str, Any]:
    return derive_topology(spec, tenant_key="default", deployment_key="local")


def test_primitives_become_services() -> None:
    derived = _derive(_spec())
    assert set(derived["services"]) == {"receiptgate-main", "asyncgate-main", "memorygate-main"}
    assert derived["services"]["asyncgate-main"]["endpoint"] == "http://asyncgate:8080/mcp"
    assert derived["services"]["asyncgate-main"]["config"]["lease_ttl_seconds"] == 300


def test_capabilities_derived_from_primitive_types() -> None:
    derived = _derive(_spec())
    allowed = derived["capabilities"]["allowed"]
    assert "receipts.submit" in allowed
    assert "tasks.lease" in allowed
    assert "memory.read" in allowed
    # Nothing in the spec grants cognition; capabilities must not be invented.
    assert "cognition.execute" not in allowed


def test_keys_are_scoped_by_problemata_and_version() -> None:
    """Derived keys, not caller-supplied ones, so two problemata cannot collide."""
    derived = _derive(_spec())
    assert derived["manifest_key"] == "problemata:demo-curation:0.1.0:manifest"
    assert derived["profile_key"] == "problemata:demo-curation:0.1.0:profile"
    assert derived["principal_key"] == "principal-demo"


def test_new_version_produces_distinct_keys() -> None:
    spec = _spec()
    spec["problemata"]["version"] = "0.2.0"
    assert _derive(spec)["manifest_key"] == "problemata:demo-curation:0.2.0:manifest"


def test_topology_edges_are_carried_into_environment() -> None:
    """Components should be able to see the mesh they were bootstrapped into."""
    derived = _derive(_spec())
    assert derived["environment"]["topology"] == _spec()["topology"]
    assert derived["environment"]["problemata_id"] == "demo-curation"


def test_memory_map_populated_only_from_memorygate() -> None:
    derived = _derive(_spec())
    assert set(derived["memory_map"]) == {"memorygate-main"}


def test_policies_become_profile_policy() -> None:
    assert _derive(_spec())["policy"] == _spec()["policies"]


def test_derivation_is_deterministic() -> None:
    """Same spec must derive the same records, or re-registration is not idempotent."""
    assert _derive(_spec()) == _derive(_spec())


@pytest.mark.parametrize("missing", ["problemata", "primitives"])
def test_missing_required_sections_rejected(missing: str) -> None:
    spec = _spec()
    del spec[missing]
    with pytest.raises(ProblemataInstantiationError):
        _derive(spec)


@pytest.mark.parametrize("field", ["id", "owner_principal"])
def test_missing_problemata_identity_rejected(field: str) -> None:
    spec = _spec()
    del spec["problemata"][field]
    with pytest.raises(ProblemataInstantiationError):
        _derive(spec)


def test_empty_primitives_rejected() -> None:
    spec = _spec()
    spec["primitives"] = {}
    with pytest.raises(ProblemataInstantiationError):
        _derive(spec)


def test_unknown_primitive_type_contributes_no_capabilities() -> None:
    """An unrecognised type is described but grants nothing."""
    spec = _spec()
    spec["primitives"] = {"mystery": {"type": "somethingelse", "endpoint": "http://x/mcp"}}
    derived = _derive(spec)
    assert derived["services"]["mystery"]["type"] == "somethingelse"
    assert derived["capabilities"]["allowed"] == []


@pytest.mark.parametrize(
    "validation,expected",
    [
        ({"status": "passed"}, True),
        ({"status": "PASSED"}, True),
        ({"status": "failed"}, False),
        ({"errors": []}, False),
        (None, False),
        ("passed", False),
    ],
)
def test_validation_attestation_gate(validation: Any, expected: bool) -> None:
    """MetaGate does not validate specs, but refuses unattested ones."""
    assert _validation_passed(validation) is expected


@pytest.mark.parametrize(
    "forbidden_key",
    ["tasks", "jobs", "work_items", "payloads", "deploy", "scale", "provision", "execute"],
)
def test_orchestration_keys_are_forbidden(forbidden_key: str) -> None:
    """MetaGate is describe-only.

    A spec carrying orchestration keys is trying to turn the bootstrap
    authority into an orchestrator, and must be refused rather than described.
    """
    from metagate.services.bootstrap import check_forbidden_keys

    spec = _spec()
    spec[forbidden_key] = {"anything": True}
    assert check_forbidden_keys(spec) == {forbidden_key}


def test_nested_orchestration_keys_are_caught() -> None:
    """Detection reports the dotted path, not the bare key."""
    from metagate.services.bootstrap import check_forbidden_keys

    spec = _spec()
    spec["primitives"]["asyncgate-main"]["config"]["tasks"] = [{"id": 1}]
    assert check_forbidden_keys(spec) == {"primitives.asyncgate-main.config.tasks"}


def test_orchestration_keys_inside_lists_are_caught() -> None:
    """A Problemata spec carries topology as a list of dicts.

    Without descending into list elements, a forbidden key one level inside any
    topology edge would pass the describe-only guard unnoticed.
    """
    from metagate.services.bootstrap import check_forbidden_keys

    spec = _spec()
    spec["topology"][0]["execute"] = {"cmd": "rm -rf /"}
    assert check_forbidden_keys(spec) == {"topology[0].execute"}


def test_clean_spec_has_no_forbidden_keys() -> None:
    from metagate.services.bootstrap import check_forbidden_keys

    assert check_forbidden_keys(_spec()) == set()


def test_derivation_does_not_mutate_input() -> None:
    spec = _spec()
    before = copy.deepcopy(spec)
    _derive(spec)
    assert spec == before
