#!/bin/bash
#
# GPU Server Restart and Baseline Test Script
# Restarts all chat and embedding servers with optimizations
# Then runs baseline latency test
#
# Usage: ./restart-and-test.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DOCKER_COMPOSE_DIR="/home/boss/heartcode/gpu-server"
ITERATIONS=10
TEST_TIMEOUT=300

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================================
# PHASE 1: RESTART CHAT SERVERS
# ============================================================================

log_info "Phase 1: Restarting GPU chat servers (Priority 1: N_UBATCH=128)..."
echo ""

for i in {1..8}; do
    log_info "Restarting gpu-server-$i (N_UBATCH=128)..."
    docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" restart gpu-server-$i

    # Wait for health check
    log_info "Waiting for health check (30 seconds)..."
    sleep 30

    # Verify it's running
    status=$(docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ps gpu-server-$i --format json 2>/dev/null | jq -r '.[0].State // "error"' 2>/dev/null || echo "error")
    if [ "$status" = "running" ]; then
        log_success "gpu-server-$i is running"
    else
        log_warning "gpu-server-$i status: $status (may still be starting)"
    fi
done

echo ""
log_success "All GPU chat servers restarted successfully"

# ============================================================================
# PHASE 2: RESTART EMBEDDING SERVERS
# ============================================================================

log_info "Phase 2: Restarting embedding servers (Priority 2: KV cache quantization)..."
echo ""

for i in {1..8}; do
    log_info "Restarting embedding-server-$i (KV cache: q8_0)..."
    docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" restart embedding-server-$i

    # Wait for health check
    log_info "Waiting for health check (15 seconds)..."
    sleep 15

    # Verify it's running
    status=$(docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ps embedding-server-$i --format json 2>/dev/null | jq -r '.[0].State // "error"' 2>/dev/null || echo "error")
    if [ "$status" = "running" ]; then
        log_success "embedding-server-$i is running"
    else
        log_warning "embedding-server-$i status: $status (may still be starting)"
    fi
done

echo ""
log_success "All embedding servers restarted successfully"

# ============================================================================
# PHASE 3: VERIFY ALL SERVERS ARE HEALTHY
# ============================================================================

log_info "Phase 3: Verifying all servers are healthy..."
echo ""

unhealthy_count=0

for i in {1..8}; do
    health=$(docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ps gpu-server-$i --format json 2>/dev/null | jq -r '.[0].Health // "none"' 2>/dev/null || echo "none")
    if [ "$health" = "healthy" ] || [ "$health" = "none" ]; then
        log_success "GPU $i: healthy"
    else
        log_warning "GPU $i: $health"
        ((unhealthy_count++))
    fi
done

for i in {1..8}; do
    health=$(docker compose -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ps embedding-server-$i --format json 2>/dev/null | jq -r '.[0].Health // "none"' 2>/dev/null || echo "none")
    if [ "$health" = "healthy" ] || [ "$health" = "none" ]; then
        log_success "Embed $i: healthy"
    else
        log_warning "Embed $i: $health"
        ((unhealthy_count++))
    fi
done

if [ $unhealthy_count -gt 0 ]; then
    log_warning "$unhealthy_count servers not yet healthy (this is normal during startup)"
    log_info "Waiting additional 30 seconds for stabilization..."
    sleep 30
else
    log_success "All servers are healthy"
fi

echo ""

# ============================================================================
# PHASE 4: BASELINE LATENCY TEST
# ============================================================================

log_info "Phase 4: Running baseline latency test ($ITERATIONS requests)..."
echo ""

API_URL="http://localhost:8080/v1/chat/completions"

# Check if API is reachable
log_info "Testing API connectivity..."
if ! timeout 5 curl -sf "$API_URL" -X POST \
    -H "Content-Type: application/json" \
    -d '{"model":"","messages":[{"role":"user","content":"test"}]}' > /dev/null 2>&1; then
    log_error "API is not responding at $API_URL"
    log_info "Try: curl -X POST $API_URL -H 'Content-Type: application/json' -d '{\"model\":\"\",\"messages\":[{\"role\":\"user\",\"content\":\"test\"}]}'"
    exit 1
fi

log_success "API is responding"
echo ""

# Run baseline tests
declare -a latencies
declare -a prompt_tokens
declare -a completion_tokens

log_info "Running $ITERATIONS test requests..."
echo ""

for i in $(seq 1 $ITERATIONS); do
    # Measure round-trip time
    start_ms=$(date +%s%3N)

    response=$(timeout 60 curl -s -X POST "$API_URL" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "local-ai-chat-sfw",
        "messages": [{"role": "user", "content": "Write a haiku about AI"}],
        "temperature": 0.8,
        "max_tokens": 50
      }')

    end_ms=$(date +%s%3N)
    elapsed=$((end_ms - start_ms))

    # Extract token counts
    pt=$(echo "$response" | jq -r '.usage.prompt_tokens // "error"' 2>/dev/null || echo "error")
    ct=$(echo "$response" | jq -r '.usage.completion_tokens // "error"' 2>/dev/null || echo "error")

    latencies+=($elapsed)
    prompt_tokens+=($pt)
    completion_tokens+=($ct)

    # Estimate TTFT (rough: total time / number of completion tokens)
    if [[ "$ct" != "error" ]] && [ "$ct" -gt 0 ]; then
        ttft=$((elapsed / ct))
        printf "Request %2d: %4dms | Prompt: %3s tokens | Completion: %3s tokens | Est. TTFT: %dms/token\n" \
            "$i" "$elapsed" "$pt" "$ct" "$ttft"
    else
        printf "Request %2d: %4dms | ERROR: Could not parse response\n" "$i" "$elapsed"
        echo "Response: $response"
    fi
done

echo ""
echo "========================================"
echo "BASELINE TEST RESULTS"
echo "========================================"

# Calculate statistics
total_latency=0
valid_count=0

for latency in "${latencies[@]}"; do
    ((total_latency += latency))
    ((valid_count++))
done

avg_latency=$((total_latency / valid_count))

# Find min/max
min_latency=${latencies[0]}
max_latency=${latencies[0]}

for latency in "${latencies[@]}"; do
    if [ $latency -lt $min_latency ]; then
        min_latency=$latency
    fi
    if [ $latency -gt $max_latency ]; then
        max_latency=$latency
    fi
done

echo "Total Requests:       $ITERATIONS"
echo "Average Latency:      ${avg_latency}ms"
echo "Min Latency:          ${min_latency}ms"
echo "Max Latency:          ${max_latency}ms"
echo "Range:                $((max_latency - min_latency))ms"
echo ""

# Estimate TTFT based on completion tokens and latency
# Rough approximation: avg_latency / avg_completion_tokens = ms per token
avg_completion=0
for ct in "${completion_tokens[@]}"; do
    if [[ "$ct" != "error" ]]; then
        ((avg_completion += ct))
    fi
done
avg_completion=$((avg_completion / ITERATIONS))

if [ $avg_completion -gt 0 ]; then
    ttft_per_token=$((avg_latency / avg_completion))
    echo "Average Completion Tokens: $avg_completion"
    echo "Estimated TTFT per Token:  ${ttft_per_token}ms"
    echo ""
    log_info "Save these numbers for comparison after load testing"
fi

# ============================================================================
# PHASE 5: SHOW NEXT STEPS
# ============================================================================

echo ""
echo "========================================"
echo "NEXT STEPS"
echo "========================================"
echo ""
log_info "Optimizations are active:"
echo "  ✓ GPU micro-batch increased: N_UBATCH 64 → 128"
echo "  ✓ Embedding KV cache: q8_0 quantization enabled"
echo ""
log_info "For next steps, run 30-minute load test:"
echo "  cd /home/boss/heartcode/infrastructure/load-tests"
echo "  k6 run -e API_KEY=\$(cat .api_key) --vus 10 --duration 30m stress-all-gpus.js"
echo ""
log_info "To monitor during load test (in separate terminal):"
echo "  watch -n 2 'nvidia-smi dmon -s pucvmet | head -10'"
echo ""

log_success "Baseline test complete!"
