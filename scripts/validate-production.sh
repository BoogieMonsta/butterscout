#!/bin/bash
# Production Security Validation Script
# Run this before deploying to production to check for common security issues
#
# Usage: ./scripts/validate-production.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

echo "============================================================================"
echo "Butterscout Production Security Validation"
echo "============================================================================"
echo ""

# Function to print error
error() {
    echo -e "${RED}[ERROR] $1${NC}"
    ERRORS=$((ERRORS + 1))
}

# Function to print warning
warning() {
    echo -e "${YELLOW}[WARN] $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

# Function to print success
success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

# Function to print info
info() {
    echo -e "[INFO] $1"
}

# Check if .env file exists
if [ ! -f .env ]; then
    error ".env file not found. Copy .env.example and configure: cp .env.example .env"
else
    success ".env file exists"
fi

# Load .env file if it exists
if [ -f .env ]; then
    # Export variables from .env
    set -a
    source .env 2>/dev/null || true
    set +a
fi

echo ""
echo "Checking API Key Configuration..."
echo "-----------------------------------"

# Check if API key is set
if [ -z "$BS_API_KEY" ]; then
    error "BS_API_KEY is not set. Generate with: openssl rand -base64 32"
else
    # Check if API key is strong enough (at least 32 characters)
    if [ ${#BS_API_KEY} -lt 32 ]; then
        warning "BS_API_KEY is too short (${#BS_API_KEY} chars). Recommended: 32+ characters"
    else
        success "BS_API_KEY is set (${#BS_API_KEY} characters)"
    fi
fi

echo ""
echo "Checking CORS Configuration..."
echo "-----------------------------------"

# Check CORS origins
if [ "$BS_CORS_ORIGINS" = "*" ]; then
    error "BS_CORS_ORIGINS is set to '*' (allows all origins). Set specific domains for production."
else
    success "BS_CORS_ORIGINS is configured: $BS_CORS_ORIGINS"
fi

echo ""
echo "Checking SearXNG Configuration..."
echo "-----------------------------------"

# Check SearXNG secret key
if [ -f searxng-config/settings.yml ]; then
    if grep -q "INSECURE_DEFAULT_CHANGE_IN_PRODUCTION" searxng-config/settings.yml; then
        error "SearXNG secret_key is still set to default. Generate new with: openssl rand -hex 32"
    elif grep -q "changeme" searxng-config/settings.yml; then
        error "SearXNG secret_key contains 'changeme'. Update in searxng-config/settings.yml"
    else
        success "SearXNG secret_key appears to be customized"
    fi
else
    warning "searxng-config/settings.yml not found"
fi

echo ""
echo "Checking Log Level..."
echo "-----------------------------------"

# Check log level
if [ "$BS_LOG_LEVEL" = "debug" ]; then
    warning "BS_LOG_LEVEL is set to 'debug'. Consider 'info' or 'warning' for production."
elif [ -z "$BS_LOG_LEVEL" ]; then
    info "BS_LOG_LEVEL not set, will use default (info)"
else
    success "BS_LOG_LEVEL is set to: $BS_LOG_LEVEL"
fi

echo ""
echo "Checking Rate Limits..."
echo "-----------------------------------"

# Check rate limits are reasonable
if [ -n "$BS_RATE_LIMIT_PER_HOUR" ]; then
    if [ "$BS_RATE_LIMIT_PER_HOUR" -gt 1000 ]; then
        warning "BS_RATE_LIMIT_PER_HOUR is very high ($BS_RATE_LIMIT_PER_HOUR). Consider lowering for production."
    else
        success "BS_RATE_LIMIT_PER_HOUR: $BS_RATE_LIMIT_PER_HOUR"
    fi
fi

if [ -n "$BS_API_KEY_RATE_LIMIT_PER_HOUR" ]; then
    success "BS_API_KEY_RATE_LIMIT_PER_HOUR: $BS_API_KEY_RATE_LIMIT_PER_HOUR"
fi

echo ""
echo "Checking Docker Configuration..."
echo "-----------------------------------"

# Check if using production compose file
if [ -f docker-compose.prod.yml ]; then
    success "docker-compose.prod.yml exists"
    info "Deploy with: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
else
    warning "docker-compose.prod.yml not found"
fi

# Check if Dockerfile exists
if [ -f Dockerfile ]; then
    # Check if Dockerfile has HEALTHCHECK
    if grep -q "HEALTHCHECK" Dockerfile; then
        success "Dockerfile contains HEALTHCHECK"
    else
        warning "Dockerfile missing HEALTHCHECK directive"
    fi

    # Check if Dockerfile has non-root user
    if grep -q "USER" Dockerfile; then
        success "Dockerfile uses non-root USER"
    else
        error "Dockerfile missing non-root USER directive"
    fi
else
    error "Dockerfile not found"
fi

# Check .dockerignore
if [ -f .dockerignore ]; then
    success ".dockerignore file exists"

    # Check if it excludes sensitive files
    if grep -q ".env" .dockerignore; then
        success ".dockerignore excludes .env files"
    else
        warning ".dockerignore should exclude .env files"
    fi
else
    warning ".dockerignore file not found"
fi

echo ""
echo "Checking for Exposed Secrets..."
echo "-----------------------------------"

# Check if .env is in git
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    error ".env file is tracked by git! Add to .gitignore immediately."
else
    success ".env file is not tracked by git"
fi

# Check gitignore
if [ -f .gitignore ]; then
    if grep -q "^\.env$" .gitignore; then
        success ".gitignore contains .env"
    else
        warning ".gitignore should contain .env"
    fi
fi

echo ""
echo "Checking Resource Limits..."
echo "-----------------------------------"

# Check if docker-compose.yml has resource limits
if [ -f docker-compose.yml ]; then
    if grep -q "resources:" docker-compose.yml; then
        success "docker-compose.yml contains resource limits"
    else
        warning "docker-compose.yml missing resource limits"
    fi
fi

echo ""
echo "============================================================================"
echo "Validation Summary"
echo "============================================================================"

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}[ERROR] Found $ERRORS issue(s) that must be fixed before production deployment${NC}"
fi

if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}[WARN] Found $WARNINGS warning(s) - review before deploying${NC}"
fi

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}[OK] All validation checks passed!${NC}"
    echo ""
    echo "Ready for production deployment:"
    echo "  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
fi

echo ""

# Exit with error code if there are errors
if [ $ERRORS -gt 0 ]; then
    exit 1
else
    exit 0
fi
