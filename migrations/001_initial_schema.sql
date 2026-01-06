-- MetaGate v0 Initial Schema
-- Bootstrap authority for LegiVellum-compatible systems

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 6.1 principals
CREATE TABLE principals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    principal_key TEXT UNIQUE NOT NULL,
    auth_subject TEXT UNIQUE NOT NULL,
    principal_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_principals_tenant ON principals(tenant_key);
CREATE INDEX idx_principals_auth_subject ON principals(auth_subject);
CREATE INDEX idx_principals_status ON principals(status);

-- 6.2 profiles
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    profile_key TEXT UNIQUE NOT NULL,
    capabilities JSONB NOT NULL,
    policy JSONB NOT NULL,
    startup_sla_seconds INT DEFAULT 120,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_profiles_tenant ON profiles(tenant_key);

-- 6.3 manifests
CREATE TABLE manifests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    manifest_key TEXT UNIQUE NOT NULL,
    deployment_key TEXT DEFAULT 'default',
    environment JSONB NOT NULL,
    services JSONB NOT NULL,
    memory_map JSONB NOT NULL,
    polling JSONB NOT NULL,
    schemas JSONB NOT NULL,
    version INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_manifests_tenant ON manifests(tenant_key);
CREATE INDEX idx_manifests_deployment ON manifests(deployment_key);

-- 6.4 bindings
CREATE TABLE bindings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    principal_id UUID REFERENCES principals(id) ON DELETE CASCADE,
    profile_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    manifest_id UUID REFERENCES manifests(id) ON DELETE CASCADE,
    overrides JSONB,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_bindings_tenant ON bindings(tenant_key);
CREATE INDEX idx_bindings_principal ON bindings(principal_id);
CREATE INDEX idx_bindings_active ON bindings(active);
CREATE UNIQUE INDEX idx_bindings_principal_active ON bindings(principal_id) WHERE active = true;

-- 6.5 secret_refs
CREATE TABLE secret_refs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    secret_key TEXT UNIQUE NOT NULL,
    ref_kind TEXT DEFAULT 'env',
    ref_name TEXT NOT NULL,
    ref_meta JSONB,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_secret_refs_tenant ON secret_refs(tenant_key);
CREATE INDEX idx_secret_refs_status ON secret_refs(status);

-- 6.6 startup_sessions
CREATE TABLE startup_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    deployment_key TEXT DEFAULT 'default',
    subject_principal_key TEXT NOT NULL,
    component_key TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    manifest_key TEXT NOT NULL,
    packet_etag TEXT NOT NULL,
    packet_hash_redacted TEXT NOT NULL,
    status TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    deadline_at TIMESTAMPTZ,
    ready_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    ready_payload JSONB,
    failure_payload JSONB,
    mirror_status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_startup_sessions_tenant ON startup_sessions(tenant_key);
CREATE INDEX idx_startup_sessions_deployment ON startup_sessions(deployment_key);
CREATE INDEX idx_startup_sessions_principal ON startup_sessions(subject_principal_key);
CREATE INDEX idx_startup_sessions_component ON startup_sessions(component_key);
CREATE INDEX idx_startup_sessions_status ON startup_sessions(status);
CREATE INDEX idx_startup_sessions_opened_at ON startup_sessions(opened_at);
CREATE INDEX idx_startup_sessions_mirror_status ON startup_sessions(mirror_status);

-- API Keys table for API key authentication
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT DEFAULT 'default',
    key_hash TEXT UNIQUE NOT NULL,
    principal_id UUID REFERENCES principals(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_api_keys_tenant ON api_keys(tenant_key);
CREATE INDEX idx_api_keys_principal ON api_keys(principal_id);
CREATE INDEX idx_api_keys_status ON api_keys(status);

-- Updated timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
CREATE TRIGGER update_principals_updated_at BEFORE UPDATE ON principals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_manifests_updated_at BEFORE UPDATE ON manifests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_bindings_updated_at BEFORE UPDATE ON bindings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_startup_sessions_updated_at BEFORE UPDATE ON startup_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
