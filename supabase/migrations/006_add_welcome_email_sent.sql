-- Migration: Add welcome_email_sent column to sessions table
-- Purpose: Track whether welcome email has been sent to a user's session
-- Trigger: Email is sent ONCE per user when their email is first captured during onboarding

-- Add welcome_email_sent column with default false
ALTER TABLE sessions
ADD COLUMN IF NOT EXISTS welcome_email_sent BOOLEAN DEFAULT FALSE;

-- Add index on welcome_email_sent for faster queries (optional but useful)
CREATE INDEX IF NOT EXISTS idx_sessions_welcome_email_sent ON sessions(welcome_email_sent);

COMMENT ON COLUMN sessions.welcome_email_sent IS 'Flag indicating if welcome email was sent for this session. Email is sent once per user on first login.';
