#!/bin/bash
#
# Memory Watchdog for GPU Server
# Monitors system memory and takes action before OOM crashes
#
# Actions (in order of severity):
# 1. WARN (80% used): Log warning
# 2. SHED (85% used): Stop accepting new requests (touch /tmp/shed_load)
# 3. EMERGENCY (90% used): Clear caches, restart heaviest container
# 4. CRITICAL (95% used): Restart all GPU containers
#
# Usage:
#   ./memory-watchdog.sh --daemon     # Run as daemon
#   ./memory-watchdog.sh --check      # Single check
#

set -euo pipefail

# Configuration
WARN_THRESHOLD="${WARN_THRESHOLD:-80}"
SHED_THRESHOLD="${SHED_THRESHOLD:-85}"
EMERGENCY_THRESHOLD="${EMERGENCY_THRESHOLD:-90}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-95}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
LOG_FILE="${LOG_FILE:-/var/log/memory-watchdog.log}"
SHED_FLAG="/tmp/heartcode_shed_load"

# Colors (for terminal output)
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
    echo -e "$msg"
}

get_memory_percent() {
    # Get memory usage percentage
    local mem_info=$(cat /proc/meminfo)
    local total=$(echo "$mem_info" | grep MemTotal | awk '{print $2}')
    local available=$(echo "$mem_info" | grep MemAvailable | awk '{print $2}')
    local used=$((total - available))
    echo $((used * 100 / total))
}

get_swap_percent() {
    local mem_info=$(cat /proc/meminfo)
    local total=$(echo "$mem_info" | grep SwapTotal | awk '{print $2}')
    local free=$(echo "$mem_info" | grep SwapFree | awk '{print $2}')
    if [[ $total -eq 0 ]]; then
        echo 0
    else
        local used=$((total - free))
        echo $((used * 100 / total))
    fi
}

# Enable load shedding - LiteLLM will check this file
enable_load_shedding() {
    if [[ ! -f "$SHED_FLAG" ]]; then
        touch "$SHED_FLAG"
        log "LOAD SHEDDING ENABLED - System under memory pressure"
    fi
}

# Disable load shedding
disable_load_shedding() {
    if [[ -f "$SHED_FLAG" ]]; then
        rm -f "$SHED_FLAG"
        log "LOAD SHEDDING DISABLED - Memory pressure relieved"
    fi
}

# Clear system caches
clear_caches() {
    log "Clearing system caches..."
    sync
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
}

# Find and restart the container using most memory
restart_heaviest_container() {
    log "Finding heaviest container..."

    local heaviest=$(docker stats --no-stream --format "{{.MemUsage}}\t{{.Name}}" 2>/dev/null | \
        grep heartcode | \
        sort -hr | \
        head -1 | \
        awk '{print $NF}')

    if [[ -n "$heaviest" ]]; then
        log "Restarting heaviest container: $heaviest"
        docker restart "$heaviest" 2>/dev/null || true
        sleep 10
    fi
}

# Restart all GPU containers
restart_all_gpu_containers() {
    log "CRITICAL: Restarting all GPU containers"

    # Stop all GPU containers
    for i in {1..8}; do
        docker stop "local-ai-gpu-$i" 2>/dev/null &
        docker stop "local-ai-embed-$i" 2>/dev/null &
    done
    wait

    sleep 5

    # Start them back up
    for i in {1..8}; do
        docker start "local-ai-gpu-$i" 2>/dev/null &
        docker start "local-ai-embed-$i" 2>/dev/null &
    done
    wait

    log "All GPU containers restarted"
}

check_memory() {
    local mem_pct=$(get_memory_percent)
    local swap_pct=$(get_swap_percent)

    if [[ $mem_pct -ge $CRITICAL_THRESHOLD ]]; then
        log "${RED}CRITICAL${NC}: Memory at ${mem_pct}% (swap: ${swap_pct}%)"
        enable_load_shedding
        clear_caches
        restart_all_gpu_containers
        return 4
    elif [[ $mem_pct -ge $EMERGENCY_THRESHOLD ]]; then
        log "${RED}EMERGENCY${NC}: Memory at ${mem_pct}% (swap: ${swap_pct}%)"
        enable_load_shedding
        clear_caches
        restart_heaviest_container
        return 3
    elif [[ $mem_pct -ge $SHED_THRESHOLD ]]; then
        log "${YELLOW}SHED${NC}: Memory at ${mem_pct}% - enabling load shedding"
        enable_load_shedding
        return 2
    elif [[ $mem_pct -ge $WARN_THRESHOLD ]]; then
        log "${YELLOW}WARN${NC}: Memory at ${mem_pct}% (swap: ${swap_pct}%)"
        disable_load_shedding
        return 1
    else
        # All good
        disable_load_shedding
        return 0
    fi
}

daemon_mode() {
    log "Starting memory watchdog daemon"
    log "Thresholds: WARN=${WARN_THRESHOLD}% SHED=${SHED_THRESHOLD}% EMERGENCY=${EMERGENCY_THRESHOLD}% CRITICAL=${CRITICAL_THRESHOLD}%"

    # Ensure shed flag is cleared on start
    disable_load_shedding

    while true; do
        check_memory || true
        sleep "$POLL_INTERVAL"
    done
}

# Parse arguments
case "${1:-}" in
    --daemon|-d)
        daemon_mode
        ;;
    --check|-c)
        check_memory
        exit $?
        ;;
    --status|-s)
        mem_pct=$(get_memory_percent)
        swap_pct=$(get_swap_percent)
        echo "Memory: ${mem_pct}%"
        echo "Swap: ${swap_pct}%"
        if [[ -f "$SHED_FLAG" ]]; then
            echo "Load shedding: ENABLED"
        else
            echo "Load shedding: disabled"
        fi
        ;;
    --help|-h)
        echo "Usage: $0 [--daemon|--check|--status]"
        echo ""
        echo "Options:"
        echo "  --daemon   Run as daemon (for systemd)"
        echo "  --check    Single memory check"
        echo "  --status   Show current status"
        exit 0
        ;;
    *)
        echo "Usage: $0 [--daemon|--check|--status]"
        exit 1
        ;;
esac
