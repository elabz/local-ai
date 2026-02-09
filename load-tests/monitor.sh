#!/bin/bash
#
# HeartCode Load Test Monitor
# Monitors GPU, backend, and system metrics during load tests
#
# Usage:
#   ./monitor.sh                    # Start monitoring
#   ./monitor.sh --gpu-only         # Only GPU metrics (run on GPU server)
#   ./monitor.sh --no-gpu           # Skip GPU monitoring (no SSH)
#
# Output:
#   - Real-time console display
#   - CSV logs in ./logs/ directory
#

set -e

# Configuration
GPU_SERVER="${GPU_SERVER:-192.168.0.145}"
GPU_SSH_USER="${GPU_SSH_USER:-boss}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
LOG_DIR="./logs/$(date +%Y%m%d_%H%M%S)"

# Colors for terminal output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
GPU_ONLY=false
NO_GPU=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu-only) GPU_ONLY=true; shift ;;
        --no-gpu) NO_GPU=true; shift ;;
        --interval) POLL_INTERVAL="$2"; shift 2 ;;
        --gpu-server) GPU_SERVER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Create log directory
mkdir -p "$LOG_DIR"
echo "Logging to: $LOG_DIR"

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Stopping monitors...${NC}"
    kill $(jobs -p) 2>/dev/null || true
    echo -e "${GREEN}Monitoring stopped. Logs saved to: $LOG_DIR${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# GPU monitoring function (runs via SSH or locally)
monitor_gpu() {
    local log_file="$LOG_DIR/gpu_metrics.csv"
    echo "timestamp,gpu_id,gpu_uuid,temp_c,gpu_util_pct,mem_util_pct,mem_used_mb,mem_total_mb,power_w,power_limit_w" > "$log_file"

    local cmd="nvidia-smi --query-gpu=timestamp,index,gpu_uuid,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit --format=csv,noheader,nounits"

    if $GPU_ONLY; then
        # Running locally on GPU server
        while true; do
            $cmd | while read line; do
                echo "$line" >> "$log_file"
            done
            sleep "$POLL_INTERVAL"
        done
    else
        # Running remotely via SSH
        while true; do
            ssh -o ConnectTimeout=10 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cmd" 2>/dev/null | while read line; do
                echo "$line" >> "$log_file"
            done
            sleep "$POLL_INTERVAL"
        done
    fi
}

# CPU temperature monitoring function (runs via SSH or locally)
monitor_cpu_temp() {
    local log_file="$LOG_DIR/cpu_metrics.csv"
    echo "timestamp,cpu_temp_c,load_1m,load_5m,load_15m" > "$log_file"

    # Command to get CPU temp and load
    # Uses /sys/class/thermal or sensors, plus uptime for load
    local cmd='
        TEMP="N/A"
        # Try thermal_zone first (most common)
        if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
            TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
            TEMP=$((TEMP / 1000))
        # Try hwmon (lm-sensors)
        elif [ -f /sys/class/hwmon/hwmon0/temp1_input ]; then
            TEMP=$(cat /sys/class/hwmon/hwmon0/temp1_input 2>/dev/null)
            TEMP=$((TEMP / 1000))
        # Try sensors command
        elif command -v sensors &>/dev/null; then
            TEMP=$(sensors 2>/dev/null | grep -E "Core 0|Tctl|temp1" | head -1 | grep -oP "\+\K[0-9.]+" | head -1)
        fi
        LOAD=$(cat /proc/loadavg | awk "{print \$1\",\"\$2\",\"\$3}")
        echo "${TEMP},${LOAD}"
    '

    if $GPU_ONLY; then
        # Running locally on GPU server
        while true; do
            local result=$(bash -c "$cmd" 2>/dev/null)
            echo "$(date -Iseconds),$result" >> "$log_file"
            sleep "$POLL_INTERVAL"
        done
    else
        # Running remotely via SSH
        while true; do
            local result=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cmd" 2>/dev/null)
            if [[ -n "$result" ]]; then
                echo "$(date -Iseconds),$result" >> "$log_file"
            fi
            sleep "$POLL_INTERVAL"
        done
    fi
}

# Backend metrics monitoring
monitor_backend() {
    local log_file="$LOG_DIR/backend_metrics.csv"
    echo "timestamp,status,response_time_ms" > "$log_file"

    while true; do
        # Use curl's built-in timing (works on macOS and Linux)
        local result=$(curl -s -o /dev/null -w "%{http_code},%{time_total}" --max-time 5 "$BACKEND_URL/health" 2>/dev/null || echo "000,0")
        local status=$(echo "$result" | cut -d',' -f1)
        local time_sec=$(echo "$result" | cut -d',' -f2)
        # Convert seconds to milliseconds
        local response_time=$(echo "$time_sec * 1000" | bc | cut -d'.' -f1)

        echo "$(date -Iseconds),$status,$response_time" >> "$log_file"
        sleep "$POLL_INTERVAL"
    done
}

# Docker container stats monitoring
monitor_docker() {
    local log_file="$LOG_DIR/docker_stats.csv"
    echo "timestamp,container,cpu_pct,mem_usage_mb,mem_limit_mb,mem_pct,net_rx_mb,net_tx_mb" > "$log_file"

    while true; do
        docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}}" 2>/dev/null | \
        grep -E "heartcode" | while read line; do
            # Parse the docker stats output
            local ts=$(date -Iseconds)
            local container=$(echo "$line" | cut -d',' -f1)
            local cpu=$(echo "$line" | cut -d',' -f2 | tr -d '%')
            local mem_usage=$(echo "$line" | cut -d',' -f3 | cut -d'/' -f1 | tr -d ' ')
            local mem_limit=$(echo "$line" | cut -d',' -f3 | cut -d'/' -f2 | tr -d ' ')
            local mem_pct=$(echo "$line" | cut -d',' -f4 | tr -d '%')
            local net_rx=$(echo "$line" | cut -d',' -f5 | cut -d'/' -f1 | tr -d ' ')
            local net_tx=$(echo "$line" | cut -d',' -f5 | cut -d'/' -f2 | tr -d ' ')

            echo "$ts,$container,$cpu,$mem_usage,$mem_limit,$mem_pct,$net_rx,$net_tx" >> "$log_file"
        done
        sleep "$POLL_INTERVAL"
    done
}

# Prometheus metrics scraping (if available)
monitor_prometheus() {
    local log_file="$LOG_DIR/app_metrics.csv"
    echo "timestamp,metric,value" > "$log_file"

    while true; do
        local metrics=$(curl -s --max-time 5 "$BACKEND_URL/health/metrics" 2>/dev/null || echo "")
        if [[ -n "$metrics" ]]; then
            local ts=$(date -Iseconds)
            echo "$metrics" | grep -E "^heartcode_" | grep -v "^#" | while read line; do
                local metric=$(echo "$line" | awk '{print $1}')
                local value=$(echo "$line" | awk '{print $2}')
                echo "$ts,$metric,$value" >> "$log_file"
            done
        fi
        sleep "$POLL_INTERVAL"
    done
}

# Real-time display function
display_status() {
    while true; do
        # Collect all data FIRST, then clear and display (prevents blinking)
        local output=""
        local ts=$(date '+%Y-%m-%d %H:%M:%S')

        output+="${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
        output+="${BLUE}  HeartCode Load Test Monitor - ${ts}${NC}\n"
        output+="${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

        # GPU Status - collect first
        if ! $NO_GPU; then
            output+="\n${GREEN}GPU Status (${GPU_SERVER}):${NC}\n"
            output+="  ID  UUID(last)    Temp   Util   Memory         Power\n"
            output+="  --- ------------ ------ ------ -------------- --------\n"
            local gpu_data=""
            if $GPU_ONLY; then
                gpu_data=$(nvidia-smi --query-gpu=index,gpu_uuid,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader 2>/dev/null)
            else
                gpu_data=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" \
                    "nvidia-smi --query-gpu=index,gpu_uuid,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader" 2>/dev/null)
            fi

            if [[ -n "$gpu_data" ]]; then
                while IFS=',' read -r idx uuid temp util mem_used mem_total power; do
                    temp=$(echo "$temp" | tr -d ' ')
                    util=$(echo "$util" | tr -d ' %')
                    power=$(echo "$power" | tr -d ' ')
                    # Extract last segment of UUID (after last hyphen)
                    uuid_short=$(echo "$uuid" | tr -d ' ' | rev | cut -d'-' -f1 | rev)

                    if (( temp >= 85 )); then
                        temp_color=$RED
                    elif (( temp >= 80 )); then
                        temp_color=$YELLOW
                    else
                        temp_color=$GREEN
                    fi

                    output+="  $idx   ${uuid_short}  ${temp_color}${temp}°C${NC}   ${util}%    ${mem_used}/${mem_total}  ${power}\n"
                done <<< "$gpu_data"
            else
                output+="  ${RED}Cannot connect to GPU server${NC}\n"
            fi

            # CPU Status - temperature and load
            local cpu_cmd='
                TEMP="N/A"
                if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
                    TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
                    TEMP=$((TEMP / 1000))
                elif [ -f /sys/class/hwmon/hwmon0/temp1_input ]; then
                    TEMP=$(cat /sys/class/hwmon/hwmon0/temp1_input 2>/dev/null)
                    TEMP=$((TEMP / 1000))
                fi
                LOAD=$(cat /proc/loadavg | awk "{print \$1\" \"\$2\" \"\$3}")
                echo "${TEMP}|${LOAD}"
            '
            local cpu_data=""
            if $GPU_ONLY; then
                cpu_data=$(bash -c "$cpu_cmd" 2>/dev/null)
            else
                cpu_data=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cpu_cmd" 2>/dev/null)
            fi

            if [[ -n "$cpu_data" ]]; then
                local cpu_temp=$(echo "$cpu_data" | cut -d'|' -f1)
                local cpu_load=$(echo "$cpu_data" | cut -d'|' -f2)

                output+="\n${GREEN}CPU Status:${NC}\n"
                # Color code CPU temperature
                local cpu_temp_color=$GREEN
                if [[ "$cpu_temp" != "N/A" ]]; then
                    if (( cpu_temp >= 85 )); then
                        cpu_temp_color=$RED
                    elif (( cpu_temp >= 70 )); then
                        cpu_temp_color=$YELLOW
                    fi
                    output+="  Temperature: ${cpu_temp_color}${cpu_temp}°C${NC}  |  Load: ${cpu_load}\n"
                else
                    output+="  Temperature: ${YELLOW}N/A${NC}  |  Load: ${cpu_load}\n"
                fi
            fi
        fi

        # Backend Status - collect first
        if ! $GPU_ONLY; then
            local result=$(curl -s -o /dev/null -w "%{http_code},%{time_total}" --max-time 2 "$BACKEND_URL/health" 2>/dev/null || echo "000,0")
            local http_code=$(echo "$result" | cut -d',' -f1)
            local time_sec=$(echo "$result" | cut -d',' -f2)
            local latency=$(echo "$time_sec * 1000" | bc 2>/dev/null | cut -d'.' -f1)
            [[ -z "$latency" ]] && latency="0"

            output+="\n${GREEN}Backend Status:${NC}\n"
            if [[ "$http_code" == "200" ]]; then
                output+="  Health: ${GREEN}OK${NC} (${latency}ms)\n"
            else
                output+="  Health: ${RED}FAIL (HTTP $http_code)${NC}\n"
            fi

            # Docker containers - collect first
            local docker_data=$(docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null | grep -E "NAME|heartcode" | head -10)
            output+="\n${GREEN}Container Resources:${NC}\n"
            output+="$docker_data\n"
        fi

        # Log file sizes
        local log_files=$(ls -lh "$LOG_DIR"/*.csv 2>/dev/null | awk '{print "  " $9 ": " $5}')
        output+="\n${GREEN}Log Files:${NC}\n"
        if [[ -n "$log_files" ]]; then
            output+="$log_files\n"
        else
            output+="  No logs yet\n"
        fi

        output+="\n${YELLOW}Press Ctrl+C to stop monitoring${NC}\n"

        # NOW clear and display everything at once
        clear
        echo -e "$output"

        sleep "$POLL_INTERVAL"
    done
}

# Main execution
echo -e "${GREEN}Starting HeartCode Load Test Monitor${NC}"
echo "GPU Server: $GPU_SERVER"
echo "Backend URL: $BACKEND_URL"
echo "Poll Interval: ${POLL_INTERVAL}s"
echo "Log Directory: $LOG_DIR"
echo ""

# Test GPU connectivity
if ! $NO_GPU && ! $GPU_ONLY; then
    echo -n "Testing GPU server connection... "
    if ssh -o ConnectTimeout=10 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "echo ok" &>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${YELLOW}FAILED - GPU monitoring disabled${NC}"
        NO_GPU=true
    fi
fi

# Start background monitors
if ! $GPU_ONLY; then
    monitor_backend &
    monitor_docker &
    monitor_prometheus &
fi

if ! $NO_GPU; then
    monitor_gpu &
    monitor_cpu_temp &  # Also monitor CPU temperature on GPU server
fi

# Start display
display_status
