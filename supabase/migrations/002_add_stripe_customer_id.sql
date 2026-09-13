-- Migration: Add stripe_customer_id column to sessions table
-- This enables storing the Stripe customer ID for each user session
-- Used for Stripe Checkout integration (Piece 2)

-- Add stripe_customer_id column to sessions table
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS stripe_customer_id text;

-- Add index for faster lookups by user_id
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

-- Add index for Stripe customer lookups
CREATE INDEX IF NOT EXISTS idx_sessions_stripe_customer_id ON sessions(stripe_customer_id);

-- Add comment documenting the purpose
COMMENT ON COLUMN sessions.stripe_customer_id IS 'Stripe customer ID for billing integration. Created on first purchase via /api/billing/checkout';
