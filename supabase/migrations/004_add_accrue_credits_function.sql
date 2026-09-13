-- Migration: SQL function for atomic credit accrual
-- This enables thread-safe credit addition without race conditions

CREATE OR REPLACE FUNCTION accrue_credits(p_user_id text, p_credits int)
RETURNS boolean AS $$
DECLARE
    updated_count int;
BEGIN
    -- Atomic UPDATE: credits = credits + p_credits
    -- This prevents race conditions (no read-modify-write gap)
    UPDATE sessions
    SET credits = credits + p_credits
    WHERE user_id = p_user_id;

    GET DIAGNOSTICS updated_count = ROW_COUNT;

    -- Return true if a row was updated, false otherwise
    RETURN updated_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Add comment documenting the function
COMMENT ON FUNCTION accrue_credits IS 'Atomically add credits to a user session (Piece 3). Thread-safe: credits = credits + p_credits in a single SQL statement.';
