# CI/CD Deployment Guide

## How It Works

**Everything is automated** via GitHub Actions. No manual steps required.

### Architecture
1. Push to `main` branch
2. GitHub Actions builds Docker image
3. Pushes to Docker Hub
4. Triggers Dokploy webhook
5. Dokploy pulls and deploys with `docker-compose.prod.yml`
6. Containers auto-generate configs from templates at startup

### Secrets Management

**All secrets are injected at runtime** from environment variables:
- `SEARXNG_SECRET_KEY` → Auto-generates config from template at container startup
- `REDIS_PASSWORD` → Passed to both Redis and API
- `BS_API_KEY` → Optional API authentication

**No manual config file generation needed!**

---

## Setup (One Time)

### 1. GitHub Secrets

Add these secrets to your GitHub repository (Settings → Secrets → Actions):

```bash
# Docker Hub
DOCKERHUB_USERNAME=your-username
DOCKERHUB_TOKEN=your-access-token

# Dokploy
DOKPLOY_WEBHOOK_URL=https://your-dokploy.com/webhook/...

# Application Secrets (for Dokploy environment)
REDIS_PASSWORD=$(openssl rand -base64 32)
SEARXNG_SECRET_KEY=$(openssl rand -hex 32)
```

### 2. Dokploy Configuration

In your Dokploy Docker Compose application, set environment variables:

```bash
REDIS_PASSWORD=<from-github-secrets>
SEARXNG_SECRET_KEY=<from-github-secrets>
```

These get injected into containers automatically.

### 3. Done!

That's it. Every push to `main` now automatically deploys.

---

## How Secrets Work

### SearXNG Configuration

**At Container Startup:**
1. Entrypoint script runs: `/etc/searxng/entrypoint.sh`
2. Reads `SEARXNG_SECRET_KEY` from environment
3. Generates `settings.yml` from `settings.yml.template`
4. Starts SearXNG with generated config

**No committed secrets, no manual steps.**

### Redis Password

Passed via environment variable to both:
- Redis container: `REDIS_PASSWORD`
- API container: `BS_REDIS_URL=redis://default:${REDIS_PASSWORD}@...`

---

## Local Development

Just works out of the box:

```bash
# No secrets needed - container auto-generates them
docker compose up
```

The entrypoint auto-generates a random secret if `SEARXNG_SECRET_KEY` is not set.

---

## Deployment Workflow

### Every Deployment
```bash
git add .
git commit -m "Your changes"
git push origin main
```

GitHub Actions handles the rest:
1. ✅ Build image
2. ✅ Push to Docker Hub
3. ✅ Trigger Dokploy webhook
4. ✅ Dokploy pulls and deploys
5. ✅ Containers generate configs at startup

### Manual Deploy (if needed)
```bash
# Trigger Dokploy webhook manually
curl -X POST $DOKPLOY_WEBHOOK_URL
```

---

## File Structure

```
searxng-config/
├── settings.yml.template  → Committed (with __SEARXNG_SECRET_KEY__ placeholder)
├── settings.yml          → Generated at runtime (gitignored, never committed)
└── entrypoint.sh         → Generates settings.yml at container startup
```

---

## Production Checklist

- [ ] GitHub Secrets configured (`DOCKERHUB_*`, `DOKPLOY_WEBHOOK_URL`)
- [ ] Dokploy environment variables set (`REDIS_PASSWORD`, `SEARXNG_SECRET_KEY`)
- [ ] `.github/workflows/deploy.yml` is active
- [ ] First deployment successful
- [ ] Health check passes: `curl https://your-domain.com/health`

---

## Troubleshooting

### "Secret key not found" in SearXNG logs
**Cause:** `SEARXNG_SECRET_KEY` not set in Dokploy environment

**Fix:** Add to Dokploy application environment variables

### Deployment not triggering
**Cause:** Webhook URL not set or incorrect

**Fix:** Check GitHub Actions logs, verify `DOKPLOY_WEBHOOK_URL` secret

### Services not starting in order
**Cause:** Health checks failing

**Fix:** Check individual service logs in Dokploy

---

## Comparison: Before vs After

| Aspect | Manual (Before) | CI/CD (Now) |
|--------|----------------|-------------|
| Deploy process | 5 manual steps | `git push` |
| Secret management | Manual sed commands | Auto-injected env vars |
| Config generation | Run script every time | Auto at startup |
| Risk of errors | High (manual) | Low (automated) |
| Works with CI/CD | ❌ No | ✅ Yes |

---

## Advanced: Updating Secrets

If you need to rotate secrets:

1. Generate new secret:
   ```bash
   openssl rand -hex 32
   ```

2. Update in Dokploy environment variables

3. Restart services:
   ```bash
   # In Dokploy UI or via API
   docker compose -f docker-compose.prod.yml restart searxng
   ```

New secret is picked up on restart, config regenerated automatically.
