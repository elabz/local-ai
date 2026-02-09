#!/bin/bash
# Health check script for GPU server

set -e

URL="${1:-http://localhost:8080}"

echo "Checking GPU server at $URL..."

# Health check
echo -n "Health: "
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
if [ "$HEALTH" = "200" ]; then
    echo "OK"
else
    echo "FAILED ($HEALTH)"
    exit 1
fi

# Model info
echo -n "Model: "
MODEL_INFO=$(curl -s "$URL/v1/models" | jq -r '.data[0].id // "unknown"')
echo "$MODEL_INFO"

# GPU info
echo -n "GPU: "
GPU_INFO=$(curl -s "$URL/health" | jq -r '.server_id // "unknown"')
echo "$GPU_INFO"

# Quick inference test
echo -n "Inference test: "
START=$(date +%s%N)
RESPONSE=$(curl -s "$URL/v1/completions" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "Hello", "max_tokens": 5}')
END=$(date +%s%N)
ELAPSED=$(( (END - START) / 1000000 ))

TOKENS=$(echo "$RESPONSE" | jq -r '.usage.completion_tokens // 0')
echo "OK (${ELAPSED}ms, ${TOKENS} tokens)"

echo ""
echo "Server is healthy!"
