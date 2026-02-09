#!/bin/bash
#
# HeartCode Thermal Stress Test
# Runs extended load tests (30+ minutes) to identify GPU cooling issues
#
# Usage:
#   ./thermal-stress.sh                    # Run from local machine (SSH to GPU server)
#   ./thermal-stress.sh --gpu-only         # Run on GPU server directly
#   ./thermal-stress.sh --duration 60      # Custom duration in minutes
#   ./thermal-stress.sh --no-load          # Only monitor, don't run load test
#
# Output:
#   - Real-time temperature display with color coding
#   - CSV log of temperature data with GPU UUIDs
#   - Summary of hottest GPUs at the end
#

set -e

# Configuration
GPU_SERVER="${GPU_SERVER:-192.168.0.145}"
GPU_SSH_USER="${GPU_SSH_USER:-boss}"
DURATION_MINUTES="${DURATION_MINUTES:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
LOG_DIR="./logs/thermal_$(date +%Y%m%d_%H%M%S)"

# Temperature thresholds (Celsius)
TEMP_WARNING=80
TEMP_CRITICAL=85
TEMP_EMERGENCY=90

# Colors for terminal output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
GPU_ONLY=false
NO_LOAD=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu-only) GPU_ONLY=true; shift ;;
        --no-load) NO_LOAD=true; shift ;;
        --duration) DURATION_MINUTES="$2"; shift 2 ;;
        --interval) POLL_INTERVAL="$2"; shift 2 ;;
        --gpu-server) GPU_SERVER="$2"; shift 2 ;;
        --warning) TEMP_WARNING="$2"; shift 2 ;;
        --critical) TEMP_CRITICAL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Create log directory
mkdir -p "$LOG_DIR"

# Calculate end time
END_TIME=$(($(date +%s) + DURATION_MINUTES * 60))

# Track peak temperatures per GPU
declare -A PEAK_TEMPS
declare -A GPU_UUIDS

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Stopping thermal stress test...${NC}"

    # Kill background jobs
    kill $(jobs -p) 2>/dev/null || true

    # Generate summary
    generate_summary

    echo -e "${GREEN}Test complete. Logs saved to: $LOG_DIR${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Get GPU data function
get_gpu_data() {
    local cmd="nvidia-smi --query-gpu=index,gpu_uuid,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit --format=csv,noheader,nounits"

    if $GPU_ONLY; then
        $cmd 2>/dev/null
    else
        ssh -o ConnectTimeout=5 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "$cmd" 2>/dev/null
    fi
}

# Log temperature data
log_temperature() {
    local log_file="$LOG_DIR/gpu_temps.csv"

    # Write header if file doesn't exist
    if [[ ! -f "$log_file" ]]; then
        echo "timestamp,elapsed_min,gpu_id,gpu_uuid,temp_c,util_pct,mem_used_mb,mem_total_mb,power_w,power_limit_w,status" > "$log_file"
    fi

    local elapsed_min=$(( ($(date +%s) - (END_TIME - DURATION_MINUTES * 60)) / 60 ))
    local ts=$(date -Iseconds)

    get_gpu_data | while IFS=',' read -r idx uuid temp util mem_used mem_total power power_limit; do
        # Clean values
        idx=$(echo "$idx" | tr -d ' ')
        uuid=$(echo "$uuid" | tr -d ' ')
        temp=$(echo "$temp" | tr -d ' ')
        util=$(echo "$util" | tr -d ' %')
        power=$(echo "$power" | tr -d ' ')
        power_limit=$(echo "$power_limit" | tr -d ' ')

        # Determine status
        local status="normal"
        if (( temp >= TEMP_EMERGENCY )); then
            status="EMERGENCY"
        elif (( temp >= TEMP_CRITICAL )); then
            status="CRITICAL"
        elif (( temp >= TEMP_WARNING )); then
            status="WARNING"
        fi

        echo "$ts,$elapsed_min,$idx,$uuid,$temp,$util,$mem_used,$mem_total,$power,$power_limit,$status" >> "$log_file"
    done
}

# Display status function
display_status() {
    local remaining=$((END_TIME - $(date +%s)))
    local remaining_min=$((remaining / 60))
    local remaining_sec=$((remaining % 60))
    local elapsed=$((DURATION_MINUTES * 60 - remaining))
    local elapsed_min=$((elapsed / 60))

    local output=""
    local ts=$(date '+%Y-%m-%d %H:%M:%S')

    output+="${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}\n"
    output+="${BLUE}  HeartCode Thermal Stress Test - ${ts}${NC}\n"
    output+="${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}\n"
    output+="\n"
    output+="${CYAN}Test Progress:${NC} ${elapsed_min}/${DURATION_MINUTES} minutes"
    output+="  |  ${CYAN}Remaining:${NC} ${remaining_min}m ${remaining_sec}s\n"
    output+="\n"
    output+="${GREEN}Temperature Thresholds:${NC} "
    output+="${GREEN}Normal (<${TEMP_WARNING}°C)${NC} | "
    output+="${YELLOW}Warning (${TEMP_WARNING}-${TEMP_CRITICAL}°C)${NC} | "
    output+="${RED}Critical (>${TEMP_CRITICAL}°C)${NC}\n"
    output+="\n"
    output+="${GREEN}GPU Status:${NC}\n"
    output+="  ID   UUID (Last)      Temp      Util    Memory            Power        Status\n"
    output+="  ───  ────────────  ────────  ──────  ──────────────  ─────────────  ────────\n"

    local gpu_data=$(get_gpu_data)

    if [[ -n "$gpu_data" ]]; then
        while IFS=',' read -r idx uuid temp util mem_used mem_total power power_limit; do
            # Clean values
            idx=$(echo "$idx" | tr -d ' ')
            uuid=$(echo "$uuid" | tr -d ' ')
            temp=$(echo "$temp" | tr -d ' ')
            util=$(echo "$util" | tr -d ' %')
            mem_used=$(echo "$mem_used" | tr -d ' ')
            mem_total=$(echo "$mem_total" | tr -d ' ')
            power=$(echo "$power" | tr -d ' ')
            power_limit=$(echo "$power_limit" | tr -d ' ')

            # Extract last segment of UUID (after last hyphen)
            local uuid_short=$(echo "$uuid" | rev | cut -d'-' -f1 | rev)

            # Store UUID mapping
            GPU_UUIDS[$idx]="$uuid"

            # Track peak temperature
            local current_peak=${PEAK_TEMPS[$idx]:-0}
            if (( temp > current_peak )); then
                PEAK_TEMPS[$idx]=$temp
            fi

            # Determine color and status based on temperature
            local temp_color=$GREEN
            local status="${GREEN}OK${NC}"
            if (( temp >= TEMP_EMERGENCY )); then
                temp_color=$MAGENTA
                status="${MAGENTA}EMERGENCY${NC}"
            elif (( temp >= TEMP_CRITICAL )); then
                temp_color=$RED
                status="${RED}CRITICAL${NC}"
            elif (( temp >= TEMP_WARNING )); then
                temp_color=$YELLOW
                status="${YELLOW}WARNING${NC}"
            fi

            # Format power display
            local power_display="${power}W/${power_limit}W"

            output+="  ${idx}    ${uuid_short}  ${temp_color}${temp}°C${NC}      ${util}%     ${mem_used}/${mem_total} MiB  ${power_display}   $status\n"
        done <<< "$gpu_data"
    else
        output+="  ${RED}Cannot connect to GPU server${NC}\n"
    fi

    # Show peak temperatures
    output+="\n${GREEN}Peak Temperatures This Session:${NC}\n"
    for idx in $(echo "${!PEAK_TEMPS[@]}" | tr ' ' '\n' | sort -n); do
        local peak=${PEAK_TEMPS[$idx]}
        local uuid_short=$(echo "${GPU_UUIDS[$idx]}" | rev | cut -d'-' -f1 | rev)
        local peak_color=$GREEN
        if (( peak >= TEMP_CRITICAL )); then
            peak_color=$RED
        elif (( peak >= TEMP_WARNING )); then
            peak_color=$YELLOW
        fi
        output+="  GPU $idx (${uuid_short}): ${peak_color}${peak}°C${NC}\n"
    done

    output+="\n${YELLOW}Press Ctrl+C to stop test and generate summary${NC}\n"

    # Clear and display
    clear
    echo -e "$output"
}

# Generate summary report
generate_summary() {
    local summary_file="$LOG_DIR/summary.txt"

    echo "HeartCode Thermal Stress Test Summary" > "$summary_file"
    echo "======================================" >> "$summary_file"
    echo "" >> "$summary_file"
    echo "Test Duration: ${DURATION_MINUTES} minutes" >> "$summary_file"
    echo "GPU Server: ${GPU_SERVER}" >> "$summary_file"
    echo "Date: $(date)" >> "$summary_file"
    echo "" >> "$summary_file"
    echo "Peak Temperatures by GPU:" >> "$summary_file"
    echo "-------------------------" >> "$summary_file"

    # Sort GPUs by peak temperature (descending)
    for idx in $(for k in "${!PEAK_TEMPS[@]}"; do echo "$k ${PEAK_TEMPS[$k]}"; done | sort -k2 -rn | awk '{print $1}'); do
        local peak=${PEAK_TEMPS[$idx]}
        local uuid=${GPU_UUIDS[$idx]}
        local uuid_short=$(echo "$uuid" | rev | cut -d'-' -f1 | rev)

        local status="OK"
        if (( peak >= TEMP_CRITICAL )); then
            status="NEEDS COOLING IMPROVEMENT"
        elif (( peak >= TEMP_WARNING )); then
            status="MONITOR CLOSELY"
        fi

        echo "  GPU $idx ($uuid_short): ${peak}°C - $status" >> "$summary_file"
        echo "    Full UUID: $uuid" >> "$summary_file"
    done

    echo "" >> "$summary_file"
    echo "Recommendations:" >> "$summary_file"
    echo "----------------" >> "$summary_file"

    local hot_gpus=0
    for idx in "${!PEAK_TEMPS[@]}"; do
        if (( ${PEAK_TEMPS[$idx]} >= TEMP_WARNING )); then
            ((hot_gpus++))
        fi
    done

    if (( hot_gpus > 0 )); then
        echo "- $hot_gpus GPU(s) reached warning temperature levels" >> "$summary_file"
        echo "- Consider improving cooling for GPUs listed above with status 'NEEDS COOLING IMPROVEMENT'" >> "$summary_file"
        echo "- Check fan speeds and case airflow" >> "$summary_file"
        echo "- Consider adding additional cooling or reducing power limits" >> "$summary_file"
    else
        echo "- All GPUs stayed within normal temperature range" >> "$summary_file"
        echo "- Current cooling solution is adequate for this workload" >> "$summary_file"
    fi

    echo "" >> "$summary_file"
    echo "Log files:" >> "$summary_file"
    echo "  - GPU temperature log: $LOG_DIR/gpu_temps.csv" >> "$summary_file"
    if [[ -f "$LOG_DIR/k6_output.txt" ]]; then
        echo "  - Load test output: $LOG_DIR/k6_output.txt" >> "$summary_file"
    fi

    # Display summary
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  THERMAL STRESS TEST SUMMARY${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    cat "$summary_file"
    echo ""
    echo -e "Full summary saved to: ${GREEN}$summary_file${NC}"
}

# Run load test in background
run_load_test() {
    if $NO_LOAD; then
        echo -e "${YELLOW}Skipping load test (--no-load mode)${NC}"
        return
    fi

    echo -e "${GREEN}Starting k6 load test for ${DURATION_MINUTES} minutes...${NC}"

    # Create extended duration k6 config
    local k6_script="$LOG_DIR/thermal_test.js"
    cat > "$k6_script" << 'EOFK6'
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Metrics
const errorRate = new Rate('errors');
const inferenceTime = new Trend('inference_time');

// Configuration from environment
const API_BASE = __ENV.API_BASE || 'http://localhost:8000/api/v1';
const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';
const DURATION = __ENV.DURATION || '30m';

export const options = {
    scenarios: {
        sustained_load: {
            executor: 'constant-vus',
            vus: 5,
            duration: DURATION,
        },
    },
    thresholds: {
        errors: ['rate<0.2'],  // Allow up to 20% errors for thermal test
    },
};

// Test data
const TEST_MESSAGES = [
    "Tell me a long story about a magical adventure in an enchanted forest.",
    "Explain quantum physics to me in detail with examples.",
    "What would you do if you could travel through time? Describe your adventures.",
    "Create a detailed recipe for the most elaborate meal you can imagine.",
    "Describe your perfect day from morning to night with every detail.",
];

export default function () {
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${AUTH_TOKEN}`,
    };

    // Get or create conversation
    let conversationId = null;

    // Get characters
    const charResponse = http.get(`${API_BASE}/characters?limit=10`, { headers, timeout: '30s' });
    if (charResponse.status === 200) {
        const characters = charResponse.json();
        if (characters.items && characters.items.length > 0) {
            const character = characters.items[Math.floor(Math.random() * characters.items.length)];

            // Create conversation
            const convResponse = http.post(
                `${API_BASE}/conversations`,
                JSON.stringify({ character_id: character.id }),
                { headers, timeout: '30s' }
            );

            if (convResponse.status === 201) {
                conversationId = convResponse.json().id;
            }
        }
    }

    if (!conversationId) {
        errorRate.add(1);
        sleep(5);
        return;
    }

    // Send message and wait for response (this is the GPU-intensive part)
    const message = TEST_MESSAGES[Math.floor(Math.random() * TEST_MESSAGES.length)];
    const startTime = Date.now();

    const chatResponse = http.post(
        `${API_BASE}/chat/${conversationId}/message`,
        JSON.stringify({ content: message }),
        { headers, timeout: '180s' }  // 3 minute timeout for thermal test
    );

    const elapsed = Date.now() - startTime;
    inferenceTime.add(elapsed);

    const success = check(chatResponse, {
        'message sent': (r) => r.status === 200 || r.status === 201,
    });

    errorRate.add(!success);

    // Cleanup - delete conversation
    http.del(`${API_BASE}/conversations/${conversationId}`, { headers, timeout: '30s' });

    // Short delay between requests
    sleep(2);
}
EOFK6

    # Run k6 in background
    k6 run \
        -e API_BASE="http://localhost:8000/api/v1" \
        -e AUTH_TOKEN="$(cat .auth_token 2>/dev/null || echo '')" \
        -e DURATION="${DURATION_MINUTES}m" \
        "$k6_script" > "$LOG_DIR/k6_output.txt" 2>&1 &

    echo -e "${GREEN}Load test running in background. Output: $LOG_DIR/k6_output.txt${NC}"
}

# Main execution
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        HeartCode Thermal Stress Test                          ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Configuration:"
echo "  GPU Server:    $GPU_SERVER"
echo "  Duration:      ${DURATION_MINUTES} minutes"
echo "  Poll Interval: ${POLL_INTERVAL}s"
echo "  Warning Temp:  ${TEMP_WARNING}°C"
echo "  Critical Temp: ${TEMP_CRITICAL}°C"
echo "  Log Directory: $LOG_DIR"
echo ""

# Test GPU connectivity
if ! $GPU_ONLY; then
    echo -n "Testing GPU server connection... "
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "${GPU_SSH_USER}@${GPU_SERVER}" "nvidia-smi > /dev/null 2>&1" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        echo "Cannot connect to GPU server. Use --gpu-only if running locally on GPU server."
        exit 1
    fi
fi

# Start load test
run_load_test

echo ""
echo -e "${YELLOW}Starting thermal monitoring for ${DURATION_MINUTES} minutes...${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop early and generate summary${NC}"
sleep 2

# Main monitoring loop
while [[ $(date +%s) -lt $END_TIME ]]; do
    log_temperature
    display_status
    sleep "$POLL_INTERVAL"
done

# Test complete
cleanup
