"""Tenant scoping helpers for MetaGate admin operations (MCP)."""

from metagate.auth.auth import AuthenticatedPrincipal
from metagate.config import get_settings


def resolve_tenant_key(auth: AuthenticatedPrincipal, requested: str | None) -> str:
    """Resolve tenant key with optional cross-tenant access."""
    settings = get_settings()
    if settings.admin_allow_cross_tenant:
        return requested or auth.principal.tenant_key
    if requested and requested != auth.principal.tenant_key:
        raise ValueError("Cross-tenant admin access denied")
    return auth.principal.tenant_key


def apply_tenant_scope(query, auth: AuthenticatedPrincipal, model):
    """Apply tenant scoping to a query when cross-tenant access is disabled."""
    settings = get_settings()
    if settings.admin_allow_cross_tenant:
        return query
    return query.where(model.tenant_key == auth.principal.tenant_key)
