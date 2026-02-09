#!/bin/bash
#
# GPU Individual Stress Test
# Tests each GPU independently to identify faulty hardware
#
# Usage:
#   ./gpu-stress-test.sh              # Test all GPUs sequentially
#   ./gpu-stress-test.sh --gpu 3      # Test specific GPU
#   ./gpu-stress-test.sh --quick      # Quick 2-min test per GPU
#   ./gpu-stress-test.sh --full       # Full 10-min test per GPU
#

set -euo pipefail

# Configuration
DURATION="${DURATION:-300}"  # 5 minutes default
LITELLM_URL="${LITELLM_URL:-http://localhost:4000}"
LITELLM_KEY="${LITELLM_KEY:-sk-local-ai-dev}"
LOG_DIR="${LOG_DIR:-/tmp/gpu-stress-test}"
PROMPT="Write a detailed 500-word essay about the history of artificial intelligence, covering its origins, key milestones, and future prospects."

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

# Parse arguments
TEST_GPU=""
QUICK_MODE=false
FULL_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu) TEST_GPU="$2"; shift 2 ;;
        --quick) QUICK_MODE=true; DURATION=120; shift ;;
        --full) FULL_MODE=true; DURATION=600; shift ;;
        --duration) DURATION="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--gpu N] [--quick|--full] [--duration SECONDS]"
            echo ""
            echo "Options:"
            echo "  --gpu N      Test only GPU N (0-7)"
            echo "  --quick      Quick 2-minute test per GPU"
            echo "  --full       Full 10-minute test per GPU"
            echo "  --duration S Custom duration in seconds"
            exit 0
            ;;
        *) error "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

# Get initial GPU state
get_gpu_status() {
    local gpu_id=$1
    nvidia-smi --id=$gpu_id --query-gpu=temperature.gpu,power.draw,memory.used,utilization.gpu --format=csv,noheader,nounits 2>/dev/null
}

# Check for GPU errors
check_gpu_health() {
    local gpu_id=$1
    local errors=0

    # Check if GPU responds
    if ! nvidia-smi --id=$gpu_id &>/dev/null; then
        error "GPU $gpu_id not responding!"
        return 1
    fi

    # Check for XID errors in dmesg (requires sudo)
    if command -v sudo &>/dev/null; then
        local xid_errors=$(sudo dmesg 2>/dev/null | grep -i "xid.*$gpu_id" | wc -l)
        if [[ $xid_errors -gt 0 ]]; then
            warn "GPU $gpu_id has $xid_errors XID errors in dmesg"
            errors=$((errors + xid_errors))
        fi
    fi

    return $errors
}

# Send inference request to specific GPU via direct port
stress_gpu() {
    local gpu_id=$1
    local port=$((8080 + gpu_id))
    local url="http://localhost:$port/v1/chat/completions"

    curl -s -X POST "$url" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"local-ai-llama\",
            \"messages\": [{\"role\": \"user\", \"content\": \"$PROMPT\"}],
            \"max_tokens\": 500,
            \"stream\": false
        }" --max-time 300 2>/dev/null
}

# Monitor GPU during test
monitor_gpu() {
    local gpu_id=$1
    local log_file="$LOG_DIR/gpu${gpu_id}_monitor.csv"

    echo "timestamp,temp_c,power_w,mem_mb,util_pct" > "$log_file"

    while true; do
        local status=$(get_gpu_status $gpu_id)
        if [[ -n "$status" ]]; then
            echo "$(date -Iseconds),$status" >> "$log_file"
        fi
        sleep 5
    done
}

# Test single GPU
test_gpu() {
    local gpu_id=$1
    local results_file="$LOG_DIR/gpu${gpu_id}_results.txt"
    local start_time=$(date +%s)
    local end_time=$((start_time + DURATION))
    local success_count=0
    local fail_count=0
    local total_time=0

    log "Testing GPU $gpu_id for ${DURATION}s..."

    # Check initial health
    if ! check_gpu_health $gpu_id; then
        error "GPU $gpu_id failed initial health check!"
        echo "FAILED: Initial health check" > "$results_file"
        return 1
    fi

    # Get baseline
    local baseline=$(get_gpu_status $gpu_id)
    log "GPU $gpu_id baseline: $baseline"

    # Start monitoring in background
    monitor_gpu $gpu_id &
    local monitor_pid=$!
    trap "kill $monitor_pid 2>/dev/null" EXIT

    # Run stress test
    while [[ $(date +%s) -lt $end_time ]]; do
        local req_start=$(date +%s%N)

        if stress_gpu $gpu_id > /dev/null 2>&1; then
            local req_end=$(date +%s%N)
            local req_time=$(( (req_end - req_start) / 1000000 ))
            total_time=$((total_time + req_time))
            success_count=$((success_count + 1))

            # Get current status
            local current=$(get_gpu_status $gpu_id)
            local temp=$(echo "$current" | cut -d',' -f1 | tr -d ' ')

            # Check for thermal issues
            if [[ $temp -gt 85 ]]; then
                warn "GPU $gpu_id temperature critical: ${temp}°C"
            elif [[ $temp -gt 80 ]]; then
                warn "GPU $gpu_id temperature high: ${temp}°C"
            fi

            echo -ne "\r  Requests: $success_count success, $fail_count failed, Temp: ${temp}°C    "
        else
            fail_count=$((fail_count + 1))
            echo -ne "\r  Requests: $success_count success, $fail_count failed    "
        fi

        sleep 1
    done

    echo ""

    # Stop monitoring
    kill $monitor_pid 2>/dev/null || true

    # Calculate results
    local avg_time=0
    if [[ $success_count -gt 0 ]]; then
        avg_time=$((total_time / success_count))
    fi

    # Get final status
    local final=$(get_gpu_status $gpu_id)
    local max_temp=$(cat "$LOG_DIR/gpu${gpu_id}_monitor.csv" 2>/dev/null | tail -n +2 | cut -d',' -f2 | sort -rn | head -1)

    # Write results
    cat > "$results_file" << EOF
GPU $gpu_id Test Results
========================
Duration: ${DURATION}s
Requests: $success_count successful, $fail_count failed
Success Rate: $(( success_count * 100 / (success_count + fail_count + 1) ))%
Avg Response Time: ${avg_time}ms
Max Temperature: ${max_temp}°C
Final Status: $final
EOF

    # Evaluate result
    local fail_rate=0
    if [[ $((success_count + fail_count)) -gt 0 ]]; then
        fail_rate=$((fail_count * 100 / (success_count + fail_count)))
    fi

    if [[ $fail_rate -gt 20 ]]; then
        error "GPU $gpu_id FAILED - ${fail_rate}% failure rate"
        return 1
    elif [[ ${max_temp:-0} -gt 85 ]]; then
        warn "GPU $gpu_id WARNING - Max temp ${max_temp}°C"
        return 2
    else
        success "GPU $gpu_id PASSED - ${success_count} requests, max ${max_temp}°C"
        return 0
    fi
}

# Main
log "GPU Individual Stress Test"
log "Duration per GPU: ${DURATION}s"
log "Log directory: $LOG_DIR"
echo ""

# Check prerequisites
if ! command -v nvidia-smi &>/dev/null; then
    error "nvidia-smi not found"
    exit 1
fi

# Get GPU count
GPU_COUNT=$(nvidia-smi --list-gpus | wc -l)
log "Found $GPU_COUNT GPUs"
echo ""

# Results tracking
declare -A RESULTS

if [[ -n "$TEST_GPU" ]]; then
    # Test single GPU
    if test_gpu "$TEST_GPU"; then
        RESULTS[$TEST_GPU]="PASS"
    else
        RESULTS[$TEST_GPU]="FAIL"
    fi
else
    # Test all GPUs sequentially
    for gpu_id in $(seq 0 $((GPU_COUNT - 1))); do
        echo ""
        echo "════════════════════════════════════════"

        if test_gpu "$gpu_id"; then
            RESULTS[$gpu_id]="PASS"
        else
            RESULTS[$gpu_id]="FAIL"
        fi

        # Cool down period between GPUs
        if [[ $gpu_id -lt $((GPU_COUNT - 1)) ]]; then
            log "Cooling down for 30s before next GPU..."
            sleep 30
        fi
    done
fi

# Summary
echo ""
echo "════════════════════════════════════════"
echo "SUMMARY"
echo "════════════════════════════════════════"

for gpu_id in "${!RESULTS[@]}"; do
    result="${RESULTS[$gpu_id]}"
    if [[ "$result" == "PASS" ]]; then
        success "GPU $gpu_id: PASS"
    else
        error "GPU $gpu_id: FAIL"
    fi
done

echo ""
log "Detailed results in: $LOG_DIR/"
