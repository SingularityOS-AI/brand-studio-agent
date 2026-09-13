-- Migration: Webhook events table and default payment method
-- This enables Stripe webhook idempotency and saved card auto-reload (Piece 3)

-- ========================================================================
-- PART 1: Webhook events table for idempotency
-- ========================================================================
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now()
);

-- Add index for faster lookups by event_type (common webhook filtering)
CREATE INDEX IF NOT EXISTS idx_webhook_events_event_type ON webhook_events(event_type);

-- Add comment documenting the purpose
COMMENT ON TABLE webhook_events IS 'Track processed Stripe webhook events for idempotency. Prevents duplicate credit accrual on Stripe retries.';
COMMENT ON COLUMN webhook_events.event_id IS 'Stripe event ID (evt_...) from webhook payload. Primary key ensures uniqueness.';
COMMENT ON COLUMN webhook_events.event_type IS 'Stripe event type (e.g., checkout.session.completed, payment_intent.succeeded).';
COMMENT ON COLUMN webhook_events.processed_at IS 'Timestamp when this webhook was processed.';

-- ========================================================================
-- PART 2: Default payment method column for auto-reload
-- ========================================================================
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS default_payment_method_id text;

-- Add index for payment method lookups
CREATE INDEX IF NOT EXISTS idx_sessions_default_payment_method_id ON sessions(default_payment_method_id);

-- Add comment documenting the purpose
COMMENT ON COLUMN sessions.default_payment_method_id IS 'Default Stripe payment method ID for auto-reload (Piece 3). Saved on first checkout via setup_intent.succeeded webhook.';

-- ========================================================================
-- PART 3: Payment pending flag for failed auto-reload
-- ========================================================================
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS payment_pending boolean DEFAULT false;

-- Add index for filtering users with pending payments
CREATE INDEX IF NOT EXISTS idx_sessions_payment_pending ON sessions(payment_pending);

-- Add comment documenting the purpose
COMMENT ON COLUMN sessions.payment_pending IS 'Flag indicating user has a failed payment requiring manual resolution (Piece 3, Q2 = A). Service blocked until resolved.';
