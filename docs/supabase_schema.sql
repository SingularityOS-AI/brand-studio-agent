-- ============================================================================
-- SUPABASE SCHEMA FOR BRAND STUDIO AGENT
--
-- Based on: spec.md Rev 3.6 (Lines 270-286: Opción B architecture)
--          plan.md (10 piezas workflow)
--          ARCHITECTURE.md (Task assignment table)
--          CONTEXTO_MAESTRO.md (Session persistence pattern from Neural Editor)
--
-- Author: Research team + Claude Code implementation
-- Date: 2026-09-05
-- Version: v1.0
--
-- This schema implements the 4-block workflow (A → B → C → D) with:
-- - Session persistence to fix "amnesia bug"
-- - Spend guard (Pieza 1) to prevent toll fraud
-- - Full workflow persistence (brand_brain, catalog, scripts, renders)
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- TABLE: users
-- Purpose: Store user metadata, credits, and subscription
-- Spec reference: spec.md lines 270-286 (Opción B mandates Rentent + Supabase)
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    -- Primary key
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    email TEXT,
    username TEXT UNIQUE,
    display_name TEXT,

    -- Credits system (critical for spend_guard Pieza 1)
    credits_balance NUMERIC(10, 2) DEFAULT 100.0 CHECK (credits_balance >= 0),
    credits_total_spent NUMERIC(10, 2) DEFAULT 0.0 CHECK (credits_total_spent >= 0),
    credits_free_tier_used BOOLEAN DEFAULT false,

    -- Subscription
    subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro', 'enterprise')),
    subscription_expires_at TIMESTAMP WITH TIME ZONE,
    subscription_auto_renew BOOLEAN DEFAULT false,

    -- Profile
    avatar_url TEXT,
    company_name TEXT,
    industry TEXT,

    -- Metadata
    onboarding_completed BOOLEAN DEFAULT false,
    onboarding_completed_at TIMESTAMP WITH TIME ZONE,

    -- Rate limiting (for spend_guard)
    ip_address INET,  -- For IP-based rate limiting
    last_request_at TIMESTAMP WITH TIME ZONE,
    requests_per_hour INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE  -- Soft delete

);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_subscription_tier ON users(subscription_tier);
CREATE INDEX IF NOT EXISTS idx_users_ip_address ON users(ip_address);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_users_updated_at();

-- ============================================================================
-- TABLE: sessions
-- Purpose: Store conversation sessions (transcripts, metadata, brand_brain)
-- Spec reference: CONTEXTO_MAESTRO.md (Session persistence pattern from Neural Editor)
-- Spec reference: spec.md lines 62-93 (Bloque A: 9 secciones extracted from interview)
-- ============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    -- Primary key
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Foreign key to user
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- Session metadata
    session_name TEXT,  -- User-defined session name
    session_type TEXT DEFAULT 'interview' CHECK (session_type IN ('interview', 'catalog', 'script', 'render')),
    session_status TEXT DEFAULT 'active' CHECK (session_status IN ('active', 'completed', 'abandoned', 'error')),

    -- Transcript (full conversation)
    transcript TEXT,
    transcript_length INTEGER DEFAULT 0,  -- Character count
    turn_count INTEGER DEFAULT 0,  -- Number of conversation turns (should be 6 for Bloque A)

    -- Metrics
    conversation_quality_score NUMERIC(2, 1) CHECK (conversation_quality_score >= 0 AND conversation_quality_score <= 10),
    duration_seconds INTEGER,  -- Session duration

    -- Brand brain (Bloque A: 9 secciones)
    brand_brain JSONB,  -- Stores complete Ralston + Segués + Noske + Gray + Hormozi data
    brand_brain_extraction_status TEXT DEFAULT 'pending' CHECK (brand_brain_extraction_status IN ('pending', 'in_progress', 'completed', 'failed')),
    brand_brain_extracted_at TIMESTAMP WITH TIME ZONE,

    -- Citation tracking (spec mandate: "Ninguna afirmación sin cita literal")
    citation_count INTEGER DEFAULT 0,
    citations JSONB,  -- Array of citations with timestamp, turn, phrase, source

    -- LLM usage tracking (for cost estimation)
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate_usd NUMERIC(10, 4) DEFAULT 0.0,

    -- Errors
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Hard reference
    CONSTRAINT valid_turn_count CHECK (turn_count >= 0 AND turn_count <= 20),
    CONSTRAINT valid_quality_score CHECK (conversation_quality_score IS NULL OR (conversation_quality_score >= 0 AND conversation_quality_score <= 10))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_session_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_sessions_session_status ON sessions(session_status);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_brand_brain_status ON sessions(brand_brain_extraction_status);

-- Brand brain index (JSONB queries)
CREATE INDEX IF NOT EXISTS idx_sessions_brand_brain ON sessions USING GIN(brand_brain);

-- Trigger for updated_at
CREATE TRIGGER trigger_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_users_updated_at();

-- ============================================================================
-- TABLE: catalogs
-- Purpose: Store 30-idea catalogs (Bloque B)
-- Spec reference: spec.md lines 86-93 (Bloque B gate duro: catálogo before script)
-- Spec reference: plan.md Pieza 3 (catalog generation prompt)
-- ============================================================================

CREATE TABLE IF NOT EXISTS catalogs (
    -- Primary key
    catalog_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Foreign keys
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,

    -- Catalog metadata
    catalog_name TEXT,
    catalog_status TEXT DEFAULT 'pending' CHECK (catalog_status IN ('pending', 'generating', 'review', 'approved', 'rejected')),
    catalog_approved_status TEXT CHECK (catalog_approved_status IN ('approved', 'needed_changes', 'rejected')),

    -- Ideas (30 ideas from Bloque B)
    ideas JSONB NOT NULL,  -- Array of 30 idea objects: {id, title, premise, category, viral_potential, citations}
    idea_count INTEGER DEFAULT 0,
    idea_generation_method TEXT DEFAULT 'llm' CHECK (idea_generation_method IN ('llm', 'manual', 'hybrid')),

    -- Market research (YouTube Data API)
    niche_analysis JSONB,  -- Results from YouTube Data API search
    niche_similarity_score NUMERIC(3, 2),  -- How similar idea is to existing viral content

    -- Approval gate (spec lines 86-93: "si el catálogo no se sostiene, no se escribe el primer guion")
    approved_idea_id UUID,  -- Which idea from catalog was chosen for Bloque C
    approved_at TIMESTAMP WITH TIME ZONE,
    approved_by TEXT,  -- 'user' (voice) or 'auto' (AI scored highest)

    -- LLM usage
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate_usd NUMERIC(10, 4) DEFAULT 0.0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_idea_count CHECK (idea_count >= 0 AND idea_count <= 100)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_catalogs_user_id ON catalogs(user_id);
CREATE INDEX IF NOT EXISTS idx_catalogs_session_id ON catalogs(session_id);
CREATE INDEX IF NOT EXISTS idx_catalogs_status ON catalogs(catalog_status);
CREATE INDEX IF NOT EXISTS idx_catalogs_approved_status ON catalogs(catalog_approved_status);
CREATE INDEX IF NOT EXISTS idx_catalogs_created_at ON catalogs(created_at);

-- Ideas index (JSONB queries)
CREATE INDEX IF NOT EXISTS idx_catalogs_ideas ON catalogs USING GIN(ideas);

-- ============================================================================
-- TABLE: scripts
-- Purpose: Store generated video scripts (Bloque C)
-- Spec reference: spec.md lines 270-286 (Bloque C: script judged by Viralidad Noir ≥9)
-- Spec reference: ARCHITECTURE.md lines 98-118 (Judge contract with forced JSON)
-- ============================================================================

CREATE TABLE IF NOT EXISTS scripts (
    -- Primary key
    script_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Foreign keys
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    catalog_id UUID NOT NULL REFERENCES catalogs(catalog_id) ON DELETE CASCADE,
    approved_idea_id UUID NOT NULL REFERENCES catalogs(catalog_id),  -- Which idea this script is from

    -- Script metadata
    script_title TEXT NOT NULL,
    script_type TEXT DEFAULT 'short_form' CHECK (script_type IN ('short_form', 'long_form', 'teaser', 'outro')),

    -- Script content
    script TEXT NOT NULL,
    script_length INTEGER,  -- Character count
    video_length_seconds INTEGER,  -- Expected video duration

    -- Viralidad Noir verdict (spec: score ≥ 9/10 for production)
    verdict JSONB NOT NULL,  -- Forced JSON from LLM Gateway: {purity, score, axes, citations}
    viral_score NUMERIC(2, 1) CHECK (viral_score >= 0 AND viral_score <= 10),  -- 0-10 score
    viral_purity TEXT CHECK (viral_purity IN ('low', 'medium', 'high')),  -- Purity classification

    -- Axes (from Viralidad Noir rubric)
    axes JSONB,  -- {emotional_intensity, pattern_recognition, contrarian_view, narrative_arc}

    -- Citations (spec mandate: "Ninguna afirmación sin cita literal")
    citations JSONB,  -- Array of citations from brand_brain + external sources
    citation_count INTEGER DEFAULT 0,

    -- Approval gate
    approved BOOLEAN DEFAULT false,  -- score ≥ 9/10 + user voice approval
    approved_at TIMESTAMP WITH TIME ZONE,
    overridden BOOLEAN DEFAULT false,  -- User override voice (allowed)
    override_reason TEXT,

    -- Revision tracking
    revision INTEGER DEFAULT 1,
    parent_script_id UUID REFERENCES scripts(script_id) ON DELETE SET NULL,

    -- LLM usage
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate_usd NUMERIC(10, 4) DEFAULT 0.0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_viral_score CHECK ((approved IS FALSE) OR (viral_score >= 9.0))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_scripts_user_id ON scripts(user_id);
CREATE INDEX IF NOT EXISTS idx_scripts_session_id ON scripts(session_id);
CREATE INDEX IF NOT EXISTS idx_scripts_catalog_id ON scripts(catalog_id);
CREATE INDEX IF NOT EXISTS idx_scripts_approved ON scripts(approved);
CREATE INDEX IF NOT EXISTS idx_scripts_viral_score ON scripts(viral_score);
CREATE INDEX IF NOT EXISTS idx_scripts_created_at ON scripts(created_at);

-- Verdict index (JSONB queries)
CREATE INDEX IF NOT EXISTS idx_scripts_verdict ON scripts USING GIN(verdict);

-- Citations index (JSONB queries)
CREATE INDEX IF NOT EXISTS idx_scripts_citations ON scripts USING GIN(citations);

-- ============================================================================
-- TABLE: renders
-- Purpose: Store video renders from HyperFaces (Bloque D)
-- Spec reference: spec.md lines 270-286 (Bloque D: render + hyperframes + artifacts)
-- Spec reference: plan.md + ARCHITECTURE.md (in-process queue pattern)
-- ============================================================================

CREATE TABLE IF NOT EXISTS renders (
    -- Primary key
    render_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Foreign keys
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    script_id UUID NOT NULL REFERENCES scripts(script_id) ON DELETE CASCADE,

    -- Render metadata
    render_name TEXT,
    render_type TEXT DEFAULT 'hyperframes' CHECK (render_type IN ('hyperframes', 'teleprompter_only', 'custom')),

    -- Render status (in-process queue)
    render_status TEXT DEFAULT 'queued' CHECK (render_status IN ('queued', 'processing', 'rendering', 'completed', 'failed')),
    render_progress NUMERIC(3, 2) DEFAULT 0.0 CHECK (render_progress >= 0 AND render_progress <= 100),

    -- HyperFrames integration
    hyperframes_project_id TEXT,
    hyperframes_composition_path TEXT,
    hyperframes_render_mode TEXT DEFAULT 'video-use',  -- From ARCHITECTURE.md

    -- Video metadata
    video_duration_seconds INTEGER,
    video_framerate INTEGER DEFAULT 30,
    video_resolution TEXT DEFAULT '1080p',  -- 1080p, 720p, 4K

    -- Artifacts (Bloque D: MP4 + title + thumbnail + shorts)
    artifacts JSONB,  -- {mp4_url, title, thumbnail_url, short_urls: [], teleprompter: true/false}

    -- Teleprompter (teleprompter integration)
    teleprompter_enabled BOOLEAN DEFAULT false,
    teleprompter_text TEXT,

    -- Render queue (in-process queue from Neural Editor pattern)
    job_queue_priority INTEGER DEFAULT 5,  -- 1 = highest
    job_queue_started_at TIMESTAMP WITH TIME ZONE,
    job_queue_completed_at TIMESTAMP WITH TIME ZONE,

    -- Errors
    error_message TEXT,
    error_count INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,

    -- LLM usage (if LLM used for render optimization)
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate_usd NUMERIC(10, 4) DEFAULT 0.0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_priority CHECK (job_queue_priority >= 1 AND job_queue_priority <= 10)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_renders_user_id ON renders(user_id);
CREATE INDEX IF NOT EXISTS idx_renders_script_id ON renders(script_id);
CREATE INDEX IF NOT EXISTS idx_renders_status ON renders(render_status);
CREATE INDEX IF NOT EXISTS idx_renders_progress ON renders(render_progress);
CREATE INDEX IF NOT EXISTS idx_renders_queue_priority ON renders(job_queue_priority);
CREATE INDEX IF NOT EXISTS idx_renders_created_at ON renders(created_at);

-- Artifacts index (JSONB queries)
CREATE INDEX IF NOT EXISTS idx_renders_artifacts ON renders USING GIN(artifacts);

-- ============================================================================
-- VIEW: studio_summary
-- Purpose: Simplified view for dashboard queries
-- ============================================================================

CREATE OR REPLACE VIEW studio_summary AS
SELECT
    u.user_id,
    u.email,
    u.display_name,
    u.credits_balance,
    u.subscription_tier,
    COUNT(s.session_id) as total_sessions,
    COUNT(sc.catalog_id) as total_catalogs,
    COUNT(scpt.script_id) as total_scripts,
    COUNT(scpt.script_id) FILTER (WHERE scpt.approved = true) as approved_scripts,
    COUNT(r.render_id) as total_renders,
    COUNT(r.render_id) FILTER (WHERE r.render_status = 'completed') as completed_renders,
    SUM(scpt.llm_tokens_used) as total_llm_tokens,
    SUM(scpt.llm_cost_estimate_usd) as total_llm_cost,
    u.created_at as member_since
FROM users u
LEFT JOIN sessions s ON u.user_id = s.user_id
LEFT JOIN catalogs sc ON s.session_id = sc.session_id
LEFT JOIN scripts scpt ON sc.catalog_id = sc.catalog_id
LEFT JOIN renders r ON scpt.script_id = r.script_id
GROUP BY u.user_id, u.email, u.display_name, u.credits_balance, u.subscription_tier, u.created_at;

-- ============================================================================
-- FUNCTION: spend_guard_check
-- Purpose: Implement Pieza 1 spend guard (rate limit + budget cap)
-- Spec reference: plan.md Pieza 1 (gate duro anti-toll fraud)
-- Usage: Called before any credit-spending operation
-- ============================================================================

CREATE OR REPLACE FUNCTION spend_guard_check(
    p_user_id UUID,
    p_estimate_cost NUMERIC,
    p_operation_type TEXT
)
RETURNS TABLE (
    allowed BOOLEAN,
    remaining_balance NUMERIC,
    reason TEXT
) AS $$
DECLARE
    v_balance NUMERIC;
    v_hour_limit INTEGER := 10;  -- Max 10 operations per hour
    v_ops_last_hour INTEGER;
BEGIN
    -- Get current balance
    SELECT credits_balance INTO v_balance
    FROM users
    WHERE user_id = p_user_id;

    -- Check budget cap (hard cutoff)
    IF v_balance < p_estimate_cost THEN
        RETURN QUERY SELECT FALSE, v_balance, 'Insufficient credits balance'::TEXT;
        RETURN;
    END IF;

    -- Check rate limit (operations per hour)
    SELECT COUNT(*) INTO v_ops_last_hour
    FROM sessions
    WHERE user_id = p_user_id
      AND created_at > NOW() - INTERVAL '1 hour';

    IF v_ops_last_hour >= v_hour_limit AND p_operation_type = 'llm_call' THEN
        RETURN QUERY SELECT FALSE, v_balance, 'Rate limit exceeded (too many operations in last hour)'::TEXT;
        RETURN;
    END IF;

    -- All checks passed
    RETURN QUERY SELECT TRUE, v_balance, NULL::TEXT;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- FUNCTION: recalculate_session_scores
-- Purpose: Recalculate quality scores and totals when transcript changes
-- ============================================================================

CREATE OR REPLACE FUNCTION recalculate_session_scores()
RETURNS VOID AS $$
BEGIN
    UPDATE sessions
    SET
        transcript_length = LENGTH(transcript),
        citation_count = COALESCE(jsonb_array_length(citations), 0),
        updated_at = NOW()
    WHERE transcript IS NOT NULL;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- FUNCTION: calculate_total_cost_estimate
-- Purpose: Calculate total cost for a full A→D cycle (for Pieza 8 measurement)
-- Spec reference: plan.md lines 219-220 (medir crédito cost after first cycle)
-- ============================================================================

CREATE OR REPLACE FUNCTION calculate_total_cost_estimate(p_session_id UUID)
RETURNS TABLE (
    total_cost_usd NUMERIC,
    cost_breakdown JSONB,
    credit_impact NUMERIC
) AS $$
DECLARE
    v_session_cost NUMERIC;
    v_catalog_cost NUMERIC;
    v_script_cost NUMERIC;
    v_render_cost NUMERIC;
    v_total_cost NUMERIC;
BREAKDOWN JSONB;
BEGIN
    -- Get session cost (Bloque A)
    SELECT COALESCE(llm_cost_estimate_usd, 0) INTO v_session_cost
    FROM sessions
    WHERE session_id = p_session_id;

    -- Get catalog cost (Bloque B)
    SELECT COALESCE(SUM(llm_cost_estimate_usd), 0) INTO v_catalog_cost
    FROM catalogs
    WHERE session_id = p_session_id;

    -- Get script cost (Bloque C)
    SELECT COALESCE(SUM(llm_cost_estimate_usd), 0) INTO v_script_cost
    FROM scripts s
    JOIN catalogs c ON s.catalog_id = c.catalog_id
    WHERE c.session_id = p_session_id;

    -- Get render cost (Bloque D)
    SELECT COALESCE(SUM(llm_cost_estimate_usd), 0) INTO v_render_cost
    FROM renders r
    JOIN scripts s ON r.script_id = s.script_id
    JOIN catalogs c ON s.catalog_id = c.catalog_id
    WHERE c.session_id = p_session_id;

    -- Calculate total
    v_total_cost := v_session_cost + v_catalog_cost + v_script_cost + v_render_cost;

    -- Build breakdown
    BREAKDOWN := jsonb_build_object(
        'bloque_a_extraction', v_session_cost,
        'bloque_b_catalog', v_catalog_cost,
        'bloque_c_script', v_script_cost,
        'bloque_d_render', v_render_cost,
        'session_id', p_session_id
    );

    RETURN QUERY SELECT v_total_cost, BREAKDOWN, v_total_cost * 100;  -- Assume $1 = 100 credits
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- COMMENTS (for documentation)
-- ============================================================================

COMMENT ON TABLE users IS 'User accounts with credits and subscription info (Opción B schema)';
COMMENT ON TABLE sessions IS 'Conversation sessions storing transcripts and Bloque A (9 secciones)';
COMMENT ON TABLE catalogs IS 'Bloque B: 30-idea catalogs with approval gate (spec lines 86-93)';
COMMENT ON TABLE scripts IS 'Bloque C: Video scripts with Viralidad Noir verdict (score ≥ 9/10)';
COMMENT ON TABLE renders IS 'Bloque D: Video renders from HyperFaces with MP4/thumbnail/shorts artifacts';
COMMENT ON FUNCTION spend_guard_check IS 'Pieza 1: Rate limit + budget cap (anti-toll fraud gate)';
COMMENT ON FUNCTION calculate_total_cost_estimate IS 'Pieza 8: Calculate real cost after first A→D cycle';

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
