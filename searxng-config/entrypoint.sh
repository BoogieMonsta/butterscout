#!/bin/sh
# SearXNG entrypoint wrapper
# Generates settings.yml from template at container startup using environment variables

set -e

TEMPLATE_FILE="/etc/searxng/settings.yml.template"
OUTPUT_FILE="/etc/searxng/settings.yml"

# Generate settings.yml from template
if [ -f "$TEMPLATE_FILE" ]; then
    echo "🔧 Generating SearXNG configuration from template..."

    # Use environment variable or generate a random secret
    if [ -z "$SEARXNG_SECRET_KEY" ]; then
        echo "⚠️  SEARXNG_SECRET_KEY not set, generating random secret (DEV ONLY!)"
        SEARXNG_SECRET_KEY=$(head -c 32 /dev/urandom | hexdump -v -e '/1 "%02x"')
    fi

    # Substitute and write
    sed "s/__SEARXNG_SECRET_KEY__/${SEARXNG_SECRET_KEY}/g" "$TEMPLATE_FILE" > "$OUTPUT_FILE"
    echo "✅ Configuration generated successfully"
else
    echo "⚠️  Template not found, using existing settings.yml"
fi

# Execute the original SearXNG entrypoint
# The actual path in the searxng container
exec /usr/local/searxng/entrypoint.sh
