#!/bin/bash
# docker-entrypoint.sh — Auto-configures the RAG platform on container start.
# Sources: /app/.env (environment variables)
# Generates: /data/.rbs_rag/config.json from env vars
# Then starts uvicorn.

set -e

# ---------------------------------------------------------------
# 1. Load .env if it exists (env vars from docker compose take precedence)
# ---------------------------------------------------------------
if [ -f /app/.env ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        if [ -z "${!key}" ]; then
            export "$key=$value"
        fi
    done < /app/.env
fi

# ---------------------------------------------------------------
# 2. Ensure data directory exists
# ---------------------------------------------------------------
DATA_DIR="${RAG_ROOT_DIR:-/data/.rbs_rag}"
mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/tenants"

# ---------------------------------------------------------------
# 3. Generate config.json from environment variables
#    This is the ONLY file that needs to change between deployments.
# ---------------------------------------------------------------
CONFIG_FILE="$DATA_DIR/config.json"

# Use env vars with defaults
LLM_API_KEY="${RAG_LLM_API_KEY:-}"
LLM_PROVIDER="${RAG_LLM_PROVIDER:-gemini}"
LLM_MODEL="${RAG_LLM_MODEL:-gemini-2.5-flash-lite}"
LLM_BASE_URL="${RAG_LLM_BASE_URL:-}"

EMBEDDING_PROVIDER="${RAG_EMBEDDING_PROVIDER:-hash}"
EMBEDDING_DIMENSIONS="${RAG_EMBEDDING_DIMENSIONS:-384}"
EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}"

QDRANT_HOST="${RAG_QDRANT_HOST:-localhost}"
QDRANT_PORT="${RAG_QDRANT_PORT:-6333}"
QDRANT_GRPC_PORT="${RAG_QDRANT_GRPC_PORT:-6334}"
QDRANT_API_KEY="${RAG_QDRANT_API_KEY:-}"
QDRANT_HTTPS="${RAG_QDRANT_HTTPS:-false}"

REDIS_HOST="${RAG_REDIS_HOST:-redis}"
REDIS_PORT="${RAG_REDIS_PORT:-6379}"
REDIS_PASSWORD="${RAG_REDIS_PASSWORD:-}"

LOG_LEVEL="${RAG_LOG_LEVEL:-INFO}"
STRUCTURED_LOGGING="${RAG_STRUCTURED_LOGGING:-true}"
ADMIN_AUTH_ENABLED="${RAG_ADMIN_AUTH_ENABLED:-false}"
CORS_ORIGINS="${RAG_CORS_ORIGINS:-[\"*\"]}"
ADMIN_JWT_SECRET="${RAG_ADMIN_JWT_SECRET:-}"
ADMIN_PASSWORD="${RAG_ADMIN_PASSWORD:-admin}"
ENCRYPTION_KEY="${RAG_ENCRYPTION_KEY:-}"

cat > "$CONFIG_FILE" << CONFIGEOF
{
  "tenant_id": "default",
  "default_kb": "default",
  "session_memory_limit": 8,
  "chat_retention_days": 30,
  "storage": {
    "provider": "sqlite",
    "path": "$DATA_DIR/rag.db"
  },
  "embeddings": {
    "provider": "$EMBEDDING_PROVIDER",
    "dimensions": $EMBEDDING_DIMENSIONS,
    "model": "$EMBEDDING_MODEL",
    "base_url": null,
    "api_key": null,
    "tier": "$EMBEDDING_PROVIDER"
  },
  "retrieval": {
    "top_k": 20,
    "rerank_top_k": 8,
    "final_context_k": 5,
    "dense_weight": 0.55,
    "sparse_weight": 0.45,
    "reranker": "bge_cross_encoder"
  },
  "chunking": {
    "max_tokens": 320,
    "overlap_tokens": 48,
    "semantic_chunking": true,
    "semantic_similarity_threshold": 0.75
  },
  "llm": {
    "provider": "$LLM_PROVIDER",
    "api_key": "${LLM_API_KEY:-}",
    "model": "$LLM_MODEL",
    "base_url": "$LLM_BASE_URL",
    "fallback_models": []
  },
  "qdrant": {
    "host": "$QDRANT_HOST",
    "port": $QDRANT_PORT,
    "grpc_port": $QDRANT_GRPC_PORT,
    "prefer_grpc": false,
    "api_key": "$QDRANT_API_KEY",
    "https": $QDRANT_HTTPS,
    "collection_config": {
      "vectors": {
        "size": $EMBEDDING_DIMENSIONS,
        "distance": "Cosine"
      },
      "optimizers_config": {
        "default_segment_number": 2
      },
      "replication_factor": 1
    }
  },
  "rate_limit": {
    "enabled": true,
    "requests_per_minute": 60,
    "burst_size": 10
  },
  "security": {
    "encrypt_keys": true,
    "admin_auth_enabled": $ADMIN_AUTH_ENABLED,
    "admin_jwt_secret": "$ADMIN_JWT_SECRET",
    "cors_origins": $CORS_ORIGINS,
    "prompt_injection_detection": true
  },
  "observability": {
    "health_endpoint": true,
    "metrics_enabled": false,
    "structured_logging": $STRUCTURED_LOGGING,
    "log_level": "$LOG_LEVEL",
    "log_file": ""
  }
}
CONFIGEOF

echo "[entrypoint] Config generated: $CONFIG_FILE"

# ---------------------------------------------------------------
# 4. Warn about LLM API key (optional — each tenant provides their own)
# ---------------------------------------------------------------
if [ -n "$LLM_API_KEY" ] && [ "$LLM_API_KEY" != "your-gemini-or-openai-api-key" ]; then
    echo "[entrypoint] Global LLM API key configured ($LLM_PROVIDER / $LLM_MODEL)"
else
    echo ""
    echo "=============================================================="
    echo "  INFO: No global RAG_LLM_API_KEY set."
    echo "  The platform starts with zero API keys."
    echo "  Each tenant will provide their own LLM API key when"
    echo "  created via the admin dashboard or API."
    echo "  This is the expected configuration for multi-tenant setups."
    echo "=============================================================="
    echo ""
fi

# ---------------------------------------------------------------
# 5. Print startup banner
# ---------------------------------------------------------------
HOSTNAME=$(hostname)
IP=$(hostname -i 2>/dev/null || echo "unknown")

echo ""
echo "=============================================================="
echo "   TenBit RAG Platform"
echo "   Container: $HOSTNAME ($IP)"
echo "   Config:    $CONFIG_FILE"
echo "   LLM:       $LLM_PROVIDER / $LLM_MODEL"
echo "   Qdrant:    ${QDRANT_HOST}:${QDRANT_PORT}"
echo "   Redis:     ${REDIS_HOST}:${REDIS_PORT}"
echo "   Encryption: ${ENCRYPTION_KEY:+enabled}${ENCRYPTION_KEY:-disabled}"
echo "   Admin Auth: ${ADMIN_JWT_SECRET:+enabled}${ADMIN_JWT_SECRET:-disabled}"
echo "=============================================================="
echo ""

# ---------------------------------------------------------------
# 6. Start uvicorn
# ---------------------------------------------------------------
exec uvicorn rbs_rag.web.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-4}" \
    --log-level "$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')" \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips '*'
