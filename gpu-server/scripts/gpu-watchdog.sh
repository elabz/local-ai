#!/bin/bash
#
# GPU Watchdog Script
# Monitors GPU VRAM and restarts containers when a GPU crashes (VRAM = 0)
#
# Usage:
#   ./gpu-watchdog.sh                    # Run once
#   ./gpu-watchdog.sh --daemon           # Run in loop (for systemd)
#
# Environment:
#   POLL_INTERVAL  - Seconds between checks (default: 30)
#   LOG_FILE       - Path to log file (default: /var/log/gpu-watchdog.log)
#   COMPOSE_FILE   - Docker compose file path
#

set -euo pipefail

# Configuration
POLL_INTERVAL="${POLL_INTERVAL:-30}"  # Check every 30s (was 5s - too frequent)
LOG_FILE="${LOG_FILE:-/var/log/gpu-watchdog.log}"
COMPOSE_FILE="${COMPOSE_FILE:-/home/boss/heartcode/gpu-server/docker-compose.yml}"
MIN_VRAM_MB="${MIN_VRAM_MB:-100}"  # Minimum VRAM to consider GPU healthy
HEALTH_CHECK_TIMEOUT="${HEALTH_CHECK_TIMEOUT:-10}"  # Allow 10s for llama-server to initialize (was 3s - too aggressive)
RESTART_COOLDOWN="${RESTART_COOLDOWN:-300}"  # Min 5 min between restarts of same GPU (prevents cascades)
RESTART_HISTORY_WINDOW="${RESTART_HISTORY_WINDOW:-600}"  # 10 min window for restart history tracking
MAX_RESTARTS_IN_WINDOW="${MAX_RESTARTS_IN_WINDOW:-3}"  # Max 3 restarts per 10 min window (circuit breaker)
ENABLE_HEALTH_CHECKS="${ENABLE_HEALTH_CHECKS:-false}"  # Disable health-based restarts by default (only VRAM-based)

# GPU to container mapping (GPU index -> container names)
# GPU 0 = gpu-server-1 + embedding-server-1, etc.
declare -A GPU_CONTAINERS=(
    [0]="local-ai-gpu-1 local-ai-embed-1"
    [1]="local-ai-gpu-2 local-ai-embed-2"
    [2]="local-ai-gpu-3 local-ai-embed-3"
    [3]="local-ai-gpu-4 local-ai-embed-4"
    [4]="local-ai-gpu-5 local-ai-embed-5"
    [5]="local-ai-gpu-6 local-ai-embed-6"
    [6]="local-ai-gpu-7 local-ai-embed-7"
    [7]="local-ai-gpu-8 local-ai-embed-8"
)

# Restart tracking: Last restart timestamp per GPU (to enforce cooldown)
declare -A LAST_RESTART_TIME=()

# Restart tracking: History of restarts per GPU (space-separated timestamps)
declare -A RESTART_HISTORY=()

# Initialize restart tracking
init_restart_tracking() {
    for gpu_idx in {0..7}; do
        LAST_RESTART_TIME[$gpu_idx]=0
        RESTART_HISTORY[$gpu_idx]=""
    done
}

log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $*" | tee -a "$LOG_FILE"
}

container_is_running() {
    local container=$1
    # Check if container process exists and is running
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"
}

check_container_health() {
    local container=$1
    local gpu_idx=$2
    local port=$((8080 + gpu_idx))  # GPU 0 = 8080, GPU 1 = 8081, etc.

    # First check if container is actually running
    if ! container_is_running "$container"; then
        return 1  # Not running
    fi

    # Try to check health endpoint with faster timeout
    if timeout "$HEALTH_CHECK_TIMEOUT" curl -sf "http://localhost:$port/health" > /dev/null 2>&1; then
        return 0  # Healthy
    else
        return 1  # Unhealthy
    fi
}

check_restart_cooldown() {
    local gpu_idx=$1
    local current_time=$(date +%s)
    local last_restart=${LAST_RESTART_TIME[$gpu_idx]:-0}
    local time_since_restart=$((current_time - last_restart))

    if (( time_since_restart < RESTART_COOLDOWN )); then
        return 1  # Restart NOT allowed (cooldown active)
    fi
    return 0  # Restart allowed (cooldown satisfied)
}

check_restart_history() {
    local gpu_idx=$1
    local current_time=$(date +%s)
    local history="${RESTART_HISTORY[$gpu_idx]:-}"

    # Clean up old timestamps outside the window
    local valid_history=""
    local restart_count=0

    if [[ -n "$history" ]]; then
        for timestamp in $history; do
            local time_diff=$((current_time - timestamp))
            if (( time_diff < RESTART_HISTORY_WINDOW )); then
                valid_history="$valid_history $timestamp"
                ((restart_count++))
            fi
        done
    fi

    # Update history with cleaned timestamps
    RESTART_HISTORY[$gpu_idx]="$valid_history"

    if (( restart_count >= MAX_RESTARTS_IN_WINDOW )); then
        return 1  # Restart NOT allowed (circuit breaker triggered)
    fi
    return 0  # Restart allowed (circuit breaker not triggered)
}

record_restart() {
    local gpu_idx=$1
    local current_time=$(date +%s)

    # Update last restart time
    LAST_RESTART_TIME[$gpu_idx]=$current_time

    # Add to restart history
    if [[ -z "${RESTART_HISTORY[$gpu_idx]}" ]]; then
        RESTART_HISTORY[$gpu_idx]="$current_time"
    else
        RESTART_HISTORY[$gpu_idx]="${RESTART_HISTORY[$gpu_idx]} $current_time"
    fi
}

is_restart_allowed() {
    local gpu_idx=$1

    # Check cooldown period first
    if ! check_restart_cooldown "$gpu_idx"; then
        return 1  # Cooldown still active
    fi

    # Check circuit breaker
    if ! check_restart_history "$gpu_idx"; then
        return 1  # Circuit breaker triggered
    fi

    return 0  # All checks passed, restart is allowed
}

check_and_restart_gpu() {
    local gpu_idx=$1
    local vram_used=$2
    local containers="${GPU_CONTAINERS[$gpu_idx]:-}"

    if [[ -z "$containers" ]]; then
        return 0
    fi

    local restart_reason=""
    local should_restart=false

    # Check 1: Any container is stopped (most critical - always restart)
    for container in $containers; do
        if ! container_is_running "$container"; then
            restart_reason="Container $container is stopped"
            should_restart=true
            break
        fi
    done

    # Check 2: VRAM below threshold (crashed/OOMKilled - always restart)
    if ! $should_restart && (( vram_used < MIN_VRAM_MB )); then
        restart_reason="VRAM is ${vram_used}MB (< ${MIN_VRAM_MB}MB threshold)"
        should_restart=true
    fi

    # Check 3: Chat server health endpoint (only if explicitly enabled - prevents restart loops)
    if ! $should_restart && [[ "$ENABLE_HEALTH_CHECKS" == "true" ]]; then
        local gpu_container="${containers%% *}"  # Get first container name (the GPU server)
        if ! check_container_health "$gpu_container" "$gpu_idx"; then
            restart_reason="Chat server health check failed (port 808$gpu_idx)"
            should_restart=true
        fi
    fi

    # Perform restart if needed and allowed
    if $should_restart; then
        # Check if restart is allowed (cooldown + circuit breaker)
        if ! is_restart_allowed "$gpu_idx"; then
            local last_restart=${LAST_RESTART_TIME[$gpu_idx]:-0}
            local current_time=$(date +%s)
            local time_since_restart=$((current_time - last_restart))

            if (( time_since_restart < RESTART_COOLDOWN )); then
                local cooldown_remaining=$((RESTART_COOLDOWN - time_since_restart))
                log "RATE_LIMIT: GPU $gpu_idx $restart_reason - Restart prevented (cooldown active: $cooldown_remaining/${RESTART_COOLDOWN}s)"
            else
                log "CIRCUIT_BREAKER: GPU $gpu_idx $restart_reason - Restart prevented (too many restarts in ${RESTART_HISTORY_WINDOW}s window)"
            fi
            return 0
        fi

        log "WARNING: GPU $gpu_idx $restart_reason - RESTARTING containers"

        for container in $containers; do
            log "  Restarting container: $container"
            if docker restart "$container" 2>&1; then
                log "  SUCCESS: $container restarted"
            else
                log "  ERROR: Failed to restart $container"
            fi
        done

        # Record this restart in history (for circuit breaker tracking)
        record_restart "$gpu_idx"

        # Wait for containers to start and stabilize
        log "  Waiting for containers to stabilize (15 seconds)..."
        sleep 15

        # Verify containers are running
        for container in $containers; do
            if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
                log "  VERIFIED: $container is running"
            else
                log "  WARN: $container may not be running"
            fi
        done

        # Verify health endpoint is responding (for chat servers)
        local gpu_server_container="${GPU_CONTAINERS[$gpu_idx]%% *}"  # Get first container (GPU server)
        sleep 5  # Extra wait for inference server to load model
        if check_container_health "$gpu_server_container" "$gpu_idx"; then
            log "  VERIFIED: Health endpoint is responding"
        else
            log "  WARN: Health endpoint still not responding (but restart completed, will check again in next cycle)"
        fi

        return 1  # Indicate a restart was performed
    fi

    return 0
}

check_all_gpus() {
    local restarts=0

    # Get GPU VRAM usage
    local gpu_data=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits 2>/dev/null)

    if [[ -z "$gpu_data" ]]; then
        log "ERROR: Could not query nvidia-smi"
        return 1
    fi

    while IFS=', ' read -r gpu_idx vram_used; do
        # Trim whitespace
        gpu_idx=$(echo "$gpu_idx" | tr -d ' ')
        vram_used=$(echo "$vram_used" | tr -d ' ')

        if ! check_and_restart_gpu "$gpu_idx" "$vram_used"; then
            ((restarts++))
        fi
    done <<< "$gpu_data"

    if (( restarts > 0 )); then
        log "Restarted containers for $restarts GPU(s)"
    fi

    return 0
}

daemon_mode() {
    # Initialize restart tracking when daemon starts
    init_restart_tracking

    log "Starting GPU watchdog daemon (interval: ${POLL_INTERVAL}s)"
    log "Monitoring GPUs 0-7 with VRAM threshold: ${MIN_VRAM_MB}MB"
    log "Restart cooldown: ${RESTART_COOLDOWN}s, Circuit breaker: ${MAX_RESTARTS_IN_WINDOW} restarts per ${RESTART_HISTORY_WINDOW}s"
    log "Health checks: $([ "$ENABLE_HEALTH_CHECKS" = "true" ] && echo "ENABLED" || echo "DISABLED")"

    while true; do
        check_all_gpus || true
        sleep "$POLL_INTERVAL"
    done
}

# Parse arguments
DAEMON_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --daemon|-d) DAEMON_MODE=true; shift ;;
        --interval) POLL_INTERVAL="$2"; shift 2 ;;
        --min-vram) MIN_VRAM_MB="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--daemon] [--interval SECONDS] [--min-vram MB]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

if $DAEMON_MODE; then
    daemon_mode
else
    log "Running single GPU check"
    check_all_gpus
fi
