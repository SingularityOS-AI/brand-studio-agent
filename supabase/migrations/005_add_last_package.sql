-- Migration 005: Add last_package column to sessions table for auto-reload
-- This column stores the last package purchased by the user (e.g., "starter", "pro", "studio")
-- When user reaches 0 credits, we auto-reload using this package

-- Add last_package column
ALTER TABLE sessions
ADD COLUMN IF NOT EXISTS last_package text;

-- Add index for faster lookups (optional but recommended)
CREATE INDEX IF NOT EXISTS idx_sessions_last_package ON sessions(last_package);

-- Add comment explaining the purpose
COMMENT ON COLUMN sessions.last_package IS 'Last purchased package (starter|pro|studio) for auto-reload when credits reach 0. Default NULL means use "starter" as fallback.';
