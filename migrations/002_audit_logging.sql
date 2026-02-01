-- MetaGate v0.2 Audit Logging Migration
-- Adds audit fields to existing tables and creates audit_log table

-- Add created_by and updated_by to principals
ALTER TABLE principals ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE principals ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- Add created_by and updated_by to profiles
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- Add created_by and updated_by to manifests
ALTER TABLE manifests ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE manifests ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- Add created_by and updated_by to bindings
ALTER TABLE bindings ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE bindings ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- Add created_by and updated_by to secret_refs
ALTER TABLE secret_refs ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE secret_refs ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- Add created_by to api_keys
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS created_by TEXT;

-- Create audit_log table for tracking security-sensitive operations
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_key TEXT NOT NULL DEFAULT 'default',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    resource_key TEXT,
    actor_principal_key TEXT NOT NULL,
    actor_ip TEXT,
    actor_user_agent TEXT,
    changes JSONB,
    metadata JSONB
);

-- Indexes for efficient audit log queries
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log(tenant_key);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_type ON audit_log(resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_id ON audit_log(resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor_principal_key);

-- Composite index for common query patterns (tenant + time range + resource type)
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_time_type ON audit_log(tenant_key, timestamp, resource_type);

-- Comment on table
COMMENT ON TABLE audit_log IS 'Immutable audit trail for security-sensitive operations on principals, profiles, manifests, and bindings';
