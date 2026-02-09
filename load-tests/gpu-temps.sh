#!/bin/bash
#
# Quick GPU Temperature Check
# Shows current GPU temperatures with device identification
#
# Usage:
#   ./gpu-temps.sh                     # Check via SSH from local machine
#   ./gpu-temps.sh --local             # Check locally on GPU server
#   ./gpu-temps.sh --watch             # Continuous monitoring (Ctrl+C to stop)
#

GPU_SERVER="${GPU_SERVER:-192.168.0.145}"
GPU_SSH_USER="${GPU_SSH_USER:-boss}"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
LOCAL=false
WATCH=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --local) LOCAL=true; shift ;;
        --watch) WATCH=true; shift ;;
        --gpu-server) GPU_SERVER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Get GPU data function
get_gpu_data() {
    local cmd="nvidia-smi --query-gpu=index,gpu_uuid,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader"

    if $LOCAL; then
        $cmd 2>/dev/null
    else
        ssh -o ConnectTimeout=5 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cmd" 2>/dev/null
    fi
}

# Display function
display_temps() {
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  GPU Temperature Status - $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${GREEN}ID${NC}   ${GREEN}UUID (Last 12)${NC}   ${GREEN}Model${NC}                    ${GREEN}Temp${NC}    ${GREEN}Util${NC}   ${GREEN}VRAM${NC}          ${GREEN}Power${NC}"
    echo "  ─── ─────────────── ───────────────────────── ─────── ────── ────────────── ────────"

    local data=$(get_gpu_data)

    if [[ -z "$data" ]]; then
        echo -e "  ${RED}Cannot connect to GPU server${NC}"
        return 1
    fi

    while IFS=',' read -r idx uuid name temp util mem_used mem_total power; do
        # Clean values
        idx=$(echo "$idx" | tr -d ' ')
        uuid=$(echo "$uuid" | tr -d ' ')
        name=$(echo "$name" | tr -d ' ' | sed 's/NVIDIA//' | sed 's/GeForce//')
        temp=$(echo "$temp" | tr -d ' ')
        util=$(echo "$util" | tr -d ' %')
        mem_used=$(echo "$mem_used" | tr -d ' ')
        mem_total=$(echo "$mem_total" | tr -d ' ')
        power=$(echo "$power" | tr -d ' ')

        # Extract last 12 chars of UUID
        local uuid_short=$(echo "$uuid" | tail -c 13)

        # Color code temperature
        local temp_color=$GREEN
        if (( temp >= 85 )); then
            temp_color=$RED
        elif (( temp >= 80 )); then
            temp_color=$YELLOW
        fi

        # Format name (truncate if needed)
        local name_fmt=$(printf "%-25s" "${name:0:25}")

        echo -e "  ${idx}    ${uuid_short}  ${name_fmt} ${temp_color}${temp}°C${NC}    ${util}%    ${mem_used}/${mem_total}  ${power}"
    done <<< "$data"

    echo ""
}

# Main
if $WATCH; then
    echo -e "${YELLOW}Watching GPU temperatures (Ctrl+C to stop)${NC}"
    while true; do
        clear
        display_temps
        sleep 5
    done
else
    display_temps
fi
