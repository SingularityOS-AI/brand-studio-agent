# 🚀 Deployment Checklist - Brand Studio Agent

## ✅ Pre-Deployment Check

### Environment Variables Required

**Critical Variables (REQUIRED for production):**
```bash
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
SUPABASE_JWT_SECRET=your-jwt-secret-here  # For ES256 mode
SUPABASE_KEY=your-service-role-key-here

# Google Cloud / Vertex AI
VERTEX_AI_PROJECT_ID=your-gcp-project-id
VERTEX_AI_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Stripe (Billing)
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxxxxxxxxxxx
STRIPE_LIVE_MODE=true

# Application Settings
ENVIRONMENT=production
TEST_MODE=false
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx  # For OpenAI fallback
```

**Optional Variables (with defaults):**
```bash
# Rate Limiting (defaults)
MAX_REQUESTS_PER_MINUTE=30
INITIAL_CREDITS=250

# Feature Flags
ENABLE_STRIPE_BILLING=true
ENABLE_VERTEX_AI=true
```

### Security Validation

1. ✅ **No secrets hardcoded** - Verified via grepping all `.py` files
2. ✅ **`.gitignore` excludes sensitive files**:
   - `.env`, `.env.local`
   - `*.pem`, `*.key` certificates
   - `*_credentials*.json`, `service-account*.json`
3. ✅ **Environment variables fail-fast** - `app/config.py` validates required vars
4. ✅ **JWT signature validation** - Both HS256 (test) and ES256 (production) supported
5. ✅ **SQL injection protection** - All queries use parameterized statements via Supabase client

### Database Migrations

Before deploying, ensure the following tables exist in Supabase:

```sql
-- Table: user_sessions
CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    credits INTEGER DEFAULT 250,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table: webhook_events
CREATE TABLE IF NOT EXISTS webhook_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE,
    event_type TEXT,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE
);

-- SQL Function: accrue_credits (atomic credit addition)
CREATE OR REPLACE FUNCTION accrue_credits(p_user_id TEXT, p_credits INTEGER)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE user_sessions
    SET credits = credits + p_credits,
        updated_at = NOW()
    WHERE user_id = p_user_id;

    RETURN EXISTS (
        SELECT 1 FROM user_sessions WHERE user_id = p_user_id
    );
END;
$$ LANGUAGE plpgsql;

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_event_id ON webhook_events(event_id);
```

## 🐳 Container Deployment (Docker)

### Dockerfile

```dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install OS dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment File for Container

Create `.env.production`:

```ini
# NEVER commit this file!
ENVIRONMENT=production
TEST_MODE=false

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret

# GCP/Vertex AI
VERTEX_AI_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/service-account.json

# Stripe
STRIPE_SECRET_KEY=sk_live_xxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxxx
STRIPE_LIVE_MODE=true

OPENAI_API_KEY=sk-xxxxxx
```

### Build and Run

```bash
# Build Docker image
docker build -t brand-studio-agent:latest .

# Run container with environment file
docker run -d \
  --name brand-studio-agent \
  --env-file .env.production \
  -p 8000:8000 \
  --restart unless-stopped \
  brand-studio-agent:latest

# View logs
docker logs -f brand-studio-agent

# Check health
curl http://localhost:8000/health
```

## ☁️ Cloud Platform Deployment

### Render (Recommended)

1. **Create PostgreSQL Database** in Render
2. **Set up Supabase** (or use Supabase directly instead)
3. **Create Web Service**:
   - Connect GitHub repo
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
4. **Environment Variables** (in Render dashboard):
   - Paste all variables from `.env.example`
   - **IMPORTANT**: Set `ENVIRONMENT=production`, `TEST_MODE=false`
5. **Deploy**

### AWS (Elastic Beanstalk)

```bash
# Install eb CLI
pip install awsebcli

# Initialize
eb init brand-studio-agent
# Select: Python, us-east-1 (or your region)

# Configure environment variables
eb setenv ENVIRONMENT=production \
         TEST_MODE=false \
         SUPABASE_URL=... \
         SUPABASE_KEY=... \
         # ... other env vars

# Deploy
eb create production-env
```

### Vercel (Serverless)

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

Add environment variables in Vercel Dashboard → Settings → Environment Variables.

## 🔒 Security Hardening

### 1. Secrets Management

- **NEVER** commit `.env` files
- Use platform-specific secret managers:
  - AWS: AWS Secrets Manager
  - Render: Built-in environment variables
  - Docker: Docker secrets or external secret manager (HashiCorp Vault)
- Rotate secrets regularly (90-day cycle for API keys)

### 2. CORS Configuration

Update `app/main.py` if needed:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Whitelist domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3. Rate Limiting

Default: 30 requests/minute per IP. Adjust in:

```python
# Override per request (requires admin/paid token)
client.get("/api/session_status", params={"skip_rate_limit": True})
```

### 4. Database Security

- Row-level security enabled in Supabase
- Service role key **NEVER** exposed to frontend
- Anon key has limited permissions
- Regular backups configured

### 5. Logging & Monitoring

```python
# Add production logging
import logging
from app.config import settings

logging.basicConfig(
    level=logging.INFO if settings.environment != "production" else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```

Monitor:
- Application logs (CloudWatch, Datadog, or platform logs)
- Database query performance
- Error rates (Sentry for error tracking)
- API response times

## 🧪 Post-Deployment Testing

### 1. Health Check

```bash
curl https://your-domain.com/health
# Expected: {"status": "healthy", "version": "1.0.0"}
```

### 2. Authentication Test

```bash
# Get JWT token (from your auth flow)
TOKEN="your-production-token"

curl -H "Authorization: Bearer $TOKEN" \
     https://your-domain.com/api/session_status
# Expected: {"credits": 250, ...}
```

### 3. Brand Brain Test

```bash
curl -H "Authorization: Bearer $TOKEN" \
     "https://your-domain.com/brand/brain?user_id=test-user"
# Expected: Brand brain JSON
```

### 4. Stripe Webhook Test

Use Stripe CLI to test webhooks:

```bash
stripe listen --forward-to localhost:8000/webhooks/stripe
stripe trigger checkout.session.completed
```

### 5. Rate Limiting Test

```bash
# Make 31 requests (should fail on #31)
for i in {1..31}; do
  curl -w "\nStatus: %{http_code}\n" \
       -H "Authorization: Bearer $TOKEN" \
       https://your-domain.com/api/session_status
done
# Expected: First 30 get 200, #31 gets 429
```

## 📊 Monitoring

### Key Metrics to Track

1. **Response Times**: P50, P95, P99 latency
2. **Error Rates**: 4xx, 5xx percentage
3. **User Engagement**: Active sessions, credit consumption
4. **Database**: Query performance, connection pool usage
5. **External APIs**: Vertex AI response times, Stripe webhook success

### Alerting

Set up alerts for:
- Error rate > 5% (for 5 consecutive minutes)
- P95 latency > 2s
- Database connection failures
- Stripe webhook failures
- Credit system errors

## 🔄 Disaster Recovery

### Backup Strategy

1. **Database Backups**: Supabase automatic daily backups + manual weekly exports
2. **Code Backups**: Git + deploy tags
3. **Configuration**: `.env` template in repo, actual secrets externalized

### Rollback Plan

```bash
# Docker rollback
docker tag brand-studio-agent:previous brand-studio-agent:latest
docker restart brand-studio-agent

# Render/Vercel rollback via dashboard
# AWS EB rollback: eb deploy --label <previous-version>
```

### Incident Response

1. Check logs immediately
2. Identify root cause (app, database, external API)
3. Rollback if critical
4. Patch and redeploy
5. Post-mortem document

## 📝 Maintenance

### Regular Tasks

- **Weekly**: Review error logs, check credit anomalies
- **Monthly**: Review and rotate API keys (if needed), update dependencies
- **Quarterly**: Security audit, performance review, capacity planning

### Dependency Updates

```bash
# Check for outdated packages
pip list --outdated

# Update requirements.txt
pip freeze > requirements.txt

# Test updates in staging before production
```

## ✅ Final Deployment Checklist

- [ ] All environment variables set and validated
- [ ] Database migrations verified
- [ ] `.env` file committed (strip secrets first)
- [ ] `.gitignore` has all sensitive files
- [ ] CORS configured for production domain
- [ ] Rate limiting tested
- [ ] Health check endpoint responds
- [ ] Authentication flow tested
- [ ] Stripe webhooks receiving events
- [ ] Vertex AI responding (or fallback working)
- [ ] Error monitoring set up (Sentry/Datadog)
- [ ] Log aggregation configured
- [ ] Backup strategy verified
- [ ] Rollback procedure tested
- [ ] Team notified of deployment
- [ ] Production URL shared with stakeholders

---

**Deployment Status**: ✅ Ready for Production

**Last Updated**: January 2025
**Version**: 1.0.0
**Contact**: For emergencies, ping DevOps on Slack (#brand-studio-alerts)
