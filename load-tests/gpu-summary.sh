#!/bin/bash
#
# GPU Temperature Summary - Sorted by temperature (hottest first)
#
# Usage:
#   ./gpu-summary.sh                # Check via SSH
#   ./gpu-summary.sh --local        # Check locally on GPU server
#

GPU_SERVER="${GPU_SERVER:-192.168.0.145}"
GPU_SSH_USER="${GPU_SSH_USER:-boss}"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Parse arguments
LOCAL=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --local) LOCAL=true; shift ;;
        --gpu-server) GPU_SERVER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Get GPU data
get_gpu_data() {
    local cmd="nvidia-smi --query-gpu=index,gpu_uuid,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits"
    if $LOCAL; then
        $cmd 2>/dev/null
    else
        ssh -o ConnectTimeout=5 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cmd" 2>/dev/null
    fi
}

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  GPU TEMPERATURE SUMMARY - $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}  Sorted by Temperature (Hottest First)${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}Rank${NC}  ${GREEN}GPU${NC}  ${GREEN}UUID (Last 12)${NC}   ${GREEN}Temp${NC}     ${GREEN}Util${NC}    ${GREEN}VRAM${NC}             ${GREEN}Power${NC}"
echo "  ────  ───  ──────────────  ───────  ──────  ───────────────  ────────"

data=$(get_gpu_data)

if [[ -z "$data" ]]; then
    echo -e "  ${RED}Cannot connect to GPU server${NC}"
    exit 1
fi

# Sort by temperature (3rd field) descending and display with rank
rank=1
echo "$data" | sort -t',' -k3 -rn | while IFS=',' read -r idx uuid temp util mem_used mem_total power; do
    # Clean values
    idx=$(echo "$idx" | tr -d ' ')
    uuid=$(echo "$uuid" | tr -d ' ')
    temp=$(echo "$temp" | tr -d ' ')
    util=$(echo "$util" | tr -d ' ')
    mem_used=$(echo "$mem_used" | tr -d ' ')
    mem_total=$(echo "$mem_total" | tr -d ' ')
    power=$(echo "$power" | tr -d ' ')

    # Extract last 12 chars of UUID
    uuid_short=$(echo "$uuid" | tail -c 13)

    # Color code temperature
    temp_color=$GREEN
    status=""
    if (( temp >= 85 )); then
        temp_color=$RED
        status=" ${RED}[CRITICAL]${NC}"
    elif (( temp >= 80 )); then
        temp_color=$YELLOW
        status=" ${YELLOW}[WARNING]${NC}"
    elif (( temp >= 70 )); then
        temp_color=$YELLOW
        status=""
    fi

    printf "  %-4s  %-3s  %-14s  ${temp_color}%3s°C${NC}    %3s%%    %5s/%5s MiB  %6sW%b\n" \
        "#$rank" "$idx" "$uuid_short" "$temp" "$util" "$mem_used" "$mem_total" "$power" "$status"

    ((rank++))
done

echo ""
echo -e "  ${GREEN}Legend:${NC} Normal (<70°C) | ${YELLOW}Warm (70-79°C)${NC} | ${YELLOW}Warning (80-84°C)${NC} | ${RED}Critical (≥85°C)${NC}"
echo ""
