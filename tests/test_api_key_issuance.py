"""Tests for issuing, listing and revoking principal API keys.

The properties worth guarding are about key material, not CRUD: a key must be
returned exactly once, never persisted in plaintext, never re-derivable from a
listing, and verifiable by the same code path that authenticates real requests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from metagate.auth.auth import verify_api_key
from metagate.models.db_models import ApiKey
from metagate.services.api_keys import (
    ApiKeyError,
    generate_api_key,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
)


def test_generated_keys_are_prefixed_and_unique() -> None:
    keys = {generate_api_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(k.startswith("mgk_") for k in keys)
    # Enough entropy that the suffix is not guessable.
    assert all(len(k) > 30 for k in keys)


@pytest.mark.asyncio
async def test_issued_key_authenticates(test_session, test_principal) -> None:
    """Issuance and verification must not drift apart."""
    result = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    api_key = result["api_key"]

    auth = await verify_api_key(api_key, test_session)
    assert auth is not None
    assert auth.principal.principal_key == test_principal.principal_key


@pytest.mark.asyncio
async def test_plaintext_key_is_never_stored(test_session, test_principal) -> None:
    result = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    api_key = result["api_key"]

    stored = (await test_session.execute(select(ApiKey))).scalars().all()
    assert len(stored) == 1
    assert stored[0].key_hash != api_key
    assert api_key not in stored[0].key_hash


@pytest.mark.asyncio
async def test_listing_never_exposes_key_material(test_session, test_principal) -> None:
    issued = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    api_key = issued["api_key"]

    listing = await list_api_keys(test_session, tenant_key="default")
    assert listing["count"] == 1
    entry = listing["api_keys"][0]
    assert "api_key" not in entry
    assert "key_hash" not in entry
    assert api_key not in str(entry)
    # Metadata that is safe and useful is still present.
    assert entry["principal_key"] == test_principal.principal_key
    assert entry["status"] == "active"


@pytest.mark.asyncio
async def test_two_issues_produce_distinct_keys(test_session, test_principal) -> None:
    first = await issue_api_key(test_session, tenant_key="default", principal_key=test_principal.principal_key)
    second = await issue_api_key(test_session, tenant_key="default", principal_key=test_principal.principal_key)
    assert first["api_key"] != second["api_key"]
    assert first["api_key_id"] != second["api_key_id"]
    # Both authenticate: reissuing does not invalidate the earlier key.
    assert await verify_api_key(first["api_key"], test_session) is not None
    assert await verify_api_key(second["api_key"], test_session) is not None


@pytest.mark.asyncio
async def test_revoked_key_stops_authenticating(test_session, test_principal) -> None:
    issued = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    await revoke_api_key(test_session, tenant_key="default", api_key_id=issued["api_key_id"])

    assert await verify_api_key(issued["api_key"], test_session) is None


@pytest.mark.asyncio
async def test_revocation_is_idempotent(test_session, test_principal) -> None:
    issued = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    first = await revoke_api_key(test_session, tenant_key="default", api_key_id=issued["api_key_id"])
    second = await revoke_api_key(test_session, tenant_key="default", api_key_id=issued["api_key_id"])
    assert first["already_revoked"] is False
    assert second["already_revoked"] is True
    assert second["status"] == "revoked"


@pytest.mark.asyncio
async def test_revocation_preserves_the_record(test_session, test_principal) -> None:
    """Revoking marks status; it must not delete the audit trail."""
    issued = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    await revoke_api_key(test_session, tenant_key="default", api_key_id=issued["api_key_id"])

    rows = (await test_session.execute(select(ApiKey))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "revoked"

    active = await list_api_keys(test_session, tenant_key="default")
    assert active["count"] == 0
    with_revoked = await list_api_keys(test_session, tenant_key="default", include_revoked=True)
    assert with_revoked["count"] == 1


@pytest.mark.asyncio
async def test_expired_key_does_not_authenticate(test_session, test_principal) -> None:
    issued = await issue_api_key(
        test_session,
        tenant_key="default",
        principal_key=test_principal.principal_key,
        expires_in_days=1,
    )
    record = (await test_session.execute(select(ApiKey))).scalars().one()
    from datetime import datetime, timedelta, timezone

    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await test_session.commit()

    assert await verify_api_key(issued["api_key"], test_session) is None


@pytest.mark.asyncio
async def test_unknown_principal_is_refused(test_session) -> None:
    with pytest.raises(ApiKeyError) as exc:
        await issue_api_key(test_session, tenant_key="default", principal_key="does-not-exist")
    assert exc.value.code == "PRINCIPAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_principal_reference_is_required(test_session) -> None:
    with pytest.raises(ApiKeyError) as exc:
        await issue_api_key(test_session, tenant_key="default")
    assert exc.value.code == "INVALID_PRINCIPAL"


@pytest.mark.asyncio
async def test_cross_tenant_issuance_is_refused(test_session, test_principal) -> None:
    """Issuing into another tenant must fail loudly, not silently succeed."""
    with pytest.raises(ApiKeyError) as exc:
        await issue_api_key(
            test_session, tenant_key="other-tenant", principal_key=test_principal.principal_key
        )
    assert exc.value.code == "TENANT_MISMATCH"


@pytest.mark.asyncio
async def test_cross_tenant_revocation_is_refused(test_session, test_principal) -> None:
    issued = await issue_api_key(
        test_session, tenant_key="default", principal_key=test_principal.principal_key
    )
    with pytest.raises(ApiKeyError) as exc:
        await revoke_api_key(
            test_session, tenant_key="other-tenant", api_key_id=issued["api_key_id"]
        )
    assert exc.value.code == "TENANT_MISMATCH"


@pytest.mark.asyncio
async def test_negative_expiry_is_refused(test_session, test_principal) -> None:
    with pytest.raises(ApiKeyError) as exc:
        await issue_api_key(
            test_session,
            tenant_key="default",
            principal_key=test_principal.principal_key,
            expires_in_days=0,
        )
    assert exc.value.code == "INVALID_EXPIRY"


@pytest.mark.asyncio
async def test_issuer_is_recorded(test_session, test_principal) -> None:
    result = await issue_api_key(
        test_session,
        tenant_key="default",
        principal_key=test_principal.principal_key,
        created_by="problemata-demo-operator",
    )
    assert result["created_by"] == "problemata-demo-operator"


@pytest.mark.asyncio
async def test_malformed_identifiers_are_refused(test_session) -> None:
    with pytest.raises(ApiKeyError) as exc:
        await issue_api_key(test_session, tenant_key="default", principal_id="not-a-uuid")
    assert exc.value.code == "INVALID_PRINCIPAL"

    with pytest.raises(ApiKeyError) as exc:
        await revoke_api_key(test_session, tenant_key="default", api_key_id="not-a-uuid")
    assert exc.value.code == "INVALID_KEY_ID"
