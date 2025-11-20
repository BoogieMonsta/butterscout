# Butterscout Deployment Guide (Dokploy)

This guide covers deploying Butterscout to a self-hosted Dokploy instance. It includes all the lessons learned from a successful production deployment.

## Prerequisites

- Dokploy instance running on a server (tested on Hetzner Ubuntu 22.04)
- Docker Hub account (for hosting images)
- GitHub repository with Actions enabled
- Server with at least 2GB RAM recommended

## Architecture

Butterscout consists of 4 services that must be deployed in this order:

1. **Redis/Valkey** - Caching layer
2. **SearXNG** - Privacy-respecting metasearch engine
3. **Crawl4AI** - Content extraction service
4. **Butterscout API** - Main application

## Deployment Approaches

Dokploy supports two deployment methods:

### 🎯 **Recommended: Docker Compose (Infrastructure as Code)**
Use `docker-compose.prod.yml` for version-controlled, reproducible deployments. This guide now focuses on this approach.

**Benefits**:
- ✅ Single source of truth in Git
- ✅ Easy to replicate across environments
- ✅ Automatic updates via CI/CD
- ✅ All configuration version-controlled

### Alternative: Manual UI Configuration
Configure each service individually in Dokploy UI. See the [Manual Service Configuration](#manual-service-configuration-legacy) section if needed.

---

## Docker Compose Deployment (Recommended)

### Prerequisites
- Dokploy instance running
- GitHub repository access configured in Dokploy
- Docker Hub account with `sesametech/butterscout:latest` image

### Deployment Steps

#### 1. Prepare Environment Variables

In Dokploy, create environment variables for your application:

```bash
# Required: Set a strong Redis password
REDIS_PASSWORD=<generate-with-openssl-rand>

# Optional: Set API key
BS_API_KEY=<your-api-key>

# Optional: Configure CORS
BS_CORS_ORIGINS=https://yourdomain.com
```

#### 2. Create Docker Compose Application

1. In Dokploy, click **Create Application**
2. Select **Docker Compose** type
3. Configure:
   - **Name**: `butterscout`
   - **Source**: GitHub repository
   - **Branch**: `main`
   - **Compose Files**: `docker-compose.yml:docker-compose.prod.yml`
   
4. Set environment variables created in step 1

5. Click **Deploy**

That's it! Dokploy will:
- Pull your repository
- Merge the compose files
- Start all services (Redis, SearXNG, Crawl4AI, API)
- Handle networking automatically

#### 3. Verify Deployment

Check service health:
```bash
curl https://your-dokploy-domain.com/health | jq
```

Expected response:
```json
{
  "status": "healthy",
  "components": {
    "valkey": {"status": "ok"},
    "cache": {"status": "ok"},
    "searxng": {"status": "ok"},
    "crawl4ai": {"status": "ok"}
  }
}
```

---

## Manual Service Configuration (Legacy)

### 1. Create Redis/Valkey Service

1. In Dokploy, create a new **Database** service
2. Select **Valkey** (or Redis)
3. Configure:
   - **Name**: `butterscout-redis` (or any name you prefer)
   - **Version**: `8-alpine` (for Valkey) or `latest` (for Redis)
   - **Custom Command**: 
     ```bash
     redis-server --save "" --appendonly no --maxmemory 512mb --maxmemory-policy allkeys-lru
     ```
   - **Internal Port**: `6379`

4. Note the **Internal Credentials** that Dokploy auto-generates:
   - Username: `default`
   - Password: (auto-generated, e.g., `n3kbqxi4tnlgpuni`)

5. Deploy and wait for service to be healthy

**⚠️ Gotcha**: Dokploy auto-generates credentials even if you don't specify them. You **must** use these credentials in dependent services.

---

### 2. Create SearXNG Service

1. Create a new **Application** service
2. Configure:
   - **Name**: `butterscout-searxng`
   - **Provider**: Docker
   - **Docker Image**: `searxng/searxng:latest`
   - **Internal Port (Container)**: `8080`

3. **CRITICAL**: Configure Bind Mount for config files

   **On your server (via SSH)**:
   ```bash
   # Create persistent config directory
   mkdir -p /opt/butterscout/searxng
   
   # Upload your settings.yml
   scp searxng-config/settings.yml root@YOUR_SERVER:/opt/butterscout/searxng/
   ```

   **In Dokploy Advanced/Volumes**:
   - Add a **Bind Mount**:
     - **Host Path**: `/opt/butterscout/searxng`
     - **Container Path**: `/etc/searxng`
     - **Type**: Bind

4. Deploy and verify logs show config is loaded (no "creating from template" message)

**⚠️ Gotcha #1**: You **must** mount the entire directory (`/opt/butterscout/searxng`), not individual files. The image defines `/etc/searxng` as a `VOLUME`, which conflicts with file-level bind mounts.

**⚠️ Gotcha #2**: Ensure `public_instance: false` in `settings.yml` unless you have a Valkey instance configured for the limiter.

**⚠️ Gotcha #3**: Do NOT include `limiter.toml` unless you have a valid schema. The limiter is optional when `limiter: false` in settings.

---

### 3. Create Crawl4AI Service

1. Create a new **Application** service
2. Configure:
   - **Name**: `butterscout-crawl4ai`
   - **Provider**: Docker
   - **Docker Image**: `unclecode/crawl4ai:latest`
   - **Internal Port (Container)**: `11235`

3. **CRITICAL**: Configure shared memory
   - In **Advanced** settings, find **Shared Memory**
   - Set to: `2147483648` (2GB in bytes)
   - Or use custom Docker run flags: `--shm-size=2gb`

4. Deploy and wait for service to be healthy

**⚠️ Gotcha**: Crawl4AI uses browser automation which requires significant shared memory. Without it, extraction will fail.

---

### 4. Create Butterscout API Service

1. Create a new **Application** service
2. Configure:
   - **Name**: `butterscout-api`
   - **Provider**: Docker
   - **Docker Image**: `sesametech/butterscout:latest` (or your Docker Hub username)

3. **Configure Environment Variables**:

   Go to the **Environment** tab and add these variables:

   ```bash
   # Service URLs (use Dokploy's auto-generated internal hostnames)
   BS_SEARXNG_URL=http://butterscout-searxng-XXXXX:8080
   BS_CRAWL4AI_URL=http://butterscout-crawl4ai-XXXXX:11235
   BS_REDIS_URL=redis://default:YOUR_AUTO_PASSWORD@butterscout-redis-XXXXX:6379/0
   
   # Cache configuration
   BS_CACHE_TYPE=redis
   BS_CACHE_TTL_SECONDS=3600
   
   # Rate limiting
   BS_RATE_LIMIT_PER_HOUR=60
   BS_API_KEY_RATE_LIMIT_PER_HOUR=600
   BS_GLOBAL_RATE_LIMIT_PER_HOUR=10000
   
   # Search configuration
   BS_MAX_RESULTS=10
   BS_MAX_CONCURRENT_EXTRACTIONS=4
   BS_EXTRACTION_TIMEOUT_MS=2500
   BS_REQUEST_TIMEOUT_MS=6000
   
   # Fallback settings
   BS_FALLBACK_ENABLED=true
   BS_FALLBACK_TIMEOUT_MS=2000
   BS_FALLBACK_MAX_WORKERS=2
   
   # Observability
   BS_LOG_LEVEL=info
   BS_ENABLE_METRICS=true
   BS_HEALTH_TIMEOUT_MS=750
   
   # CORS
   BS_CORS_ORIGINS=*
   ```

4. **Configure Port Exposure**:
   - Go to **Ports** tab
   - Add port mapping:
     - **Container Port**: `8000`
     - **Host Port**: `8000`
     - **Protocol**: TCP

5. Deploy and wait for service to be healthy

**⚠️ Gotcha #1**: The `BS_REDIS_URL` format is `redis://USERNAME:PASSWORD@host:port/db`. Note the username (`default`) before the colon!

**⚠️ Gotcha #2**: Dokploy generates unique internal hostnames for each service (e.g., `butterscout-searxng-mayfrf`). Find these in each service's details page.

**⚠️ Gotcha #3**: If you scale a service to 0 and back to 1, you may need to also restart dependent services due to Docker Swarm's port allocation.

---

## Verification

### 1. Health Check

```bash
curl http://YOUR_SERVER:8000/health | jq
```

Should return:
```json
{
  "status": "healthy",
  "components": {
    "valkey": {"status": "ok"},
    "cache": {"status": "ok"},
    "searxng": {"status": "ok"},
    "crawl4ai": {"status": "ok"}
  }
}
```

### 2. Search Test

```bash
curl -X POST http://YOUR_SERVER:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "python", "max_results": 2}' | jq
```

Should return search results with extracted content.

---

## CI/CD Integration (Optional)

### GitHub Actions Setup

1. Add Docker Hub secrets to your GitHub repository:
   - `DOCKERHUB_USERNAME`: Your Docker Hub username
   - `DOCKERHUB_TOKEN`: Docker Hub access token

2. Get the webhook URL from your Butterscout API service in Dokploy

3. Add as GitHub secret:
   - `DOKPLOY_WEBHOOK_URL`: The webhook URL from Dokploy

The `.github/workflows/deploy.yml` workflow will automatically:
- Build the Docker image on push to main
- Push to Docker Hub
- Trigger Dokploy to redeploy with the new image

---

## Troubleshooting

### SearXNG Returns 403 Forbidden

**Symptom**: `/search?format=json` returns `403 Forbidden`

**Causes**:
1. Config file not mounted correctly (check logs for "creating from template")
2. `public_instance: true` without proper limiter setup
3. Invalid `limiter.toml` schema

**Solution**:
- Verify bind mount is configured for the directory, not individual files
- Set `public_instance: false` if not using limiter
- Remove `limiter.toml` if not needed

### API Fails to Start (Redis Auth Error)

**Symptom**: `AuthenticationError: AUTH <password> called without any password configured`

**Cause**: Wrong Redis URL format

**Solution**: Ensure `BS_REDIS_URL=redis://default:PASSWORD@host:port/0` (include `default:` username)

### Crawl4AI Extraction Fails

**Symptom**: Content extraction returns errors or empty content

**Cause**: Insufficient shared memory for browser automation

**Solution**: Set shared memory to 2GB in Advanced settings

### Port Already in Use

**Symptom**: `no suitable node (host-mode port already in use on 1 node)`

**Cause**: Old container holding the port after scaling operations

**Solution**:
```bash
# Scale to 0, wait, then scale back to 1
docker service scale SERVICE_NAME=0
sleep 5
docker service scale SERVICE_NAME=1
```

---

## Security Considerations

1. **Change SearXNG secret_key**: Update the `secret_key` in `settings.yml` to a random value:
   ```bash
   openssl rand -hex 32
   ```

2. **CORS Configuration**: Update `BS_CORS_ORIGINS` to restrict allowed origins in production

3. **API Keys**: Consider enabling `BS_API_KEY` for production deployments

4. **Redis Password**: Use the auto-generated password or set a strong custom one

5. **HTTPS/Domains**: Configure custom domains with automatic HTTPS in Dokploy's "Domains" tab

---

## Maintenance

### Updating Services

To update any service:
1. Go to service in Dokploy
2. Update **Docker Image** tag (e.g., `latest` → `v1.2.3`)
3. Click **Deploy**

For the API, push to your repository's main branch and CI/CD will handle it.

### Viewing Logs

```bash
# Via Dokploy UI: Service → Logs tab

# Via SSH:
docker service logs SERVICE_NAME --tail 50 --follow
```

### Backup Configuration

Important files to backup:
- `/opt/butterscout/searxng/settings.yml` - SearXNG configuration
- Environment variables from Dokploy (export via UI or API)
- Dokploy project configuration (backup via Dokploy's export feature)

---

## Performance Tuning

### Redis/Valkey

Adjust cache settings based on your needs:
- `--maxmemory 512mb` - Increase for larger cache
- `--maxmemory-policy allkeys-lru` - Change eviction policy if needed

### API

- `BS_MAX_CONCURRENT_EXTRACTIONS`: Increase for better throughput (watch CPU/RAM)
- `BS_CACHE_TTL_SECONDS`: Increase to reduce API calls
- `BS_EXTRACTION_TIMEOUT_MS`: Increase for slow sites

### SearXNG

- Add more search engines in `settings.yml`
- Adjust `request_timeout` in `settings.yml` if searches are slow

---

## Additional Resources

- [Dokploy Documentation](https://docs.dokploy.com)
- [SearXNG Documentation](https://docs.searxng.org)
- [Crawl4AI Documentation](https://github.com/unclecode/crawl4ai)
- [Valkey Documentation](https://valkey.io/documentation)
