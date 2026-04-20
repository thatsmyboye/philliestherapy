-- Supabase schema for Phillies bot / web app
-- Run this once in the Supabase SQL editor to create the required tables.

-- Generic key-value store used by bot_state and props_state
CREATE TABLE IF NOT EXISTS kv_store (
    key         TEXT PRIMARY KEY,
    value       JSONB        NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Auto-update updated_at on every write
CREATE OR REPLACE FUNCTION _kv_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS kv_store_updated_at ON kv_store;
CREATE TRIGGER kv_store_updated_at
    BEFORE UPDATE ON kv_store
    FOR EACH ROW EXECUTE FUNCTION _kv_set_updated_at();

-- Row-level security: service_role key bypasses RLS automatically.
-- Enable RLS so anon/authenticated keys cannot read or write.
ALTER TABLE kv_store ENABLE ROW LEVEL SECURITY;
