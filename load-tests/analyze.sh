#!/bin/bash
#
# HeartCode Load Test Analyzer
# Analyzes logs from monitor.sh and generates a summary report
#
# Usage:
#   ./analyze.sh ./logs/20260109_143000    # Analyze specific log directory
#   ./analyze.sh                            # Analyze most recent logs
#

set -e

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Find log directory
if [[ -n "$1" ]]; then
    LOG_DIR="$1"
else
    LOG_DIR=$(ls -td ./logs/*/ 2>/dev/null | head -1)
fi

if [[ ! -d "$LOG_DIR" ]]; then
    echo -e "${RED}Error: Log directory not found: $LOG_DIR${NC}"
    echo "Usage: $0 [log_directory]"
    exit 1
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  HeartCode Load Test Analysis${NC}"
echo -e "${BLUE}  Log Directory: $LOG_DIR${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"

# GPU Analysis
if [[ -f "$LOG_DIR/gpu_metrics.csv" ]]; then
    echo -e "\n${GREEN}═══ GPU METRICS ═══${NC}"

    # Skip header and analyze
    tail -n +2 "$LOG_DIR/gpu_metrics.csv" | awk -F',' '
    BEGIN {
        max_temp = 0
        total_temp = 0
        max_util = 0
        total_util = 0
        max_power = 0
        total_power = 0
        count = 0
        temp_warnings = 0
        temp_critical = 0
    }
    {
        temp = $3 + 0
        util = $4 + 0
        power = $8 + 0

        if (temp > max_temp) max_temp = temp
        if (util > max_util) max_util = util
        if (power > max_power) max_power = power

        total_temp += temp
        total_util += util
        total_power += power
        count++

        if (temp >= 85) temp_critical++
        else if (temp >= 80) temp_warnings++
    }
    END {
        if (count > 0) {
            printf "  Samples: %d\n", count
            printf "\n  Temperature:\n"
            printf "    Average: %.1f°C\n", total_temp/count
            printf "    Maximum: %.1f°C", max_temp
            if (max_temp >= 85) printf " ⚠️  CRITICAL"
            else if (max_temp >= 80) printf " ⚠️  WARNING"
            else printf " ✓"
            printf "\n"
            if (temp_critical > 0) printf "    Critical Events (>85°C): %d\n", temp_critical
            if (temp_warnings > 0) printf "    Warning Events (>80°C): %d\n", temp_warnings

            printf "\n  GPU Utilization:\n"
            printf "    Average: %.1f%%\n", total_util/count
            printf "    Maximum: %.1f%%\n", max_util

            printf "\n  Power Draw:\n"
            printf "    Average: %.1fW\n", total_power/count
            printf "    Maximum: %.1fW\n", max_power
        }
    }'

    # Per-GPU breakdown
    echo -e "\n  Per-GPU Summary:"
    tail -n +2 "$LOG_DIR/gpu_metrics.csv" | awk -F',' '
    {
        gpu[$2]["count"]++
        gpu[$2]["temp"] += $3
        if ($3 > gpu[$2]["max_temp"]) gpu[$2]["max_temp"] = $3
    }
    END {
        for (g in gpu) {
            printf "    GPU %s: Avg %.1f°C, Max %.1f°C\n", g, gpu[g]["temp"]/gpu[g]["count"], gpu[g]["max_temp"]
        }
    }'
fi

# Backend Analysis
if [[ -f "$LOG_DIR/backend_metrics.csv" ]]; then
    echo -e "\n${GREEN}═══ BACKEND HEALTH ═══${NC}"

    tail -n +2 "$LOG_DIR/backend_metrics.csv" | awk -F',' '
    BEGIN {
        total_time = 0
        max_time = 0
        min_time = 999999
        success = 0
        errors = 0
        count = 0
    }
    {
        status = $2 + 0
        time = $3 + 0

        if (status == 200) success++
        else errors++

        total_time += time
        if (time > max_time) max_time = time
        if (time < min_time) min_time = time
        count++
    }
    END {
        if (count > 0) {
            printf "  Health Checks: %d\n", count
            printf "  Success Rate: %.2f%% (%d/%d)\n", (success/count)*100, success, count
            if (errors > 0) printf "  Errors: %d\n", errors
            printf "\n  Response Time:\n"
            printf "    Average: %dms\n", total_time/count
            printf "    Min: %dms\n", min_time
            printf "    Max: %dms\n", max_time
        }
    }'
fi

# Docker Stats Analysis
if [[ -f "$LOG_DIR/docker_stats.csv" ]]; then
    echo -e "\n${GREEN}═══ CONTAINER RESOURCES ═══${NC}"

    # Get unique containers
    containers=$(tail -n +2 "$LOG_DIR/docker_stats.csv" | cut -d',' -f2 | sort -u)

    for container in $containers; do
        echo -e "\n  ${BLUE}$container${NC}:"
        grep ",$container," "$LOG_DIR/docker_stats.csv" | awk -F',' '
        BEGIN {
            max_cpu = 0
            total_cpu = 0
            max_mem = 0
            count = 0
        }
        {
            cpu = $3 + 0
            # Parse memory (handle MiB, GiB, etc.)
            mem_str = $4
            mem = 0
            if (index(mem_str, "GiB") > 0) {
                gsub(/[^0-9.]/, "", mem_str)
                mem = mem_str * 1024
            } else if (index(mem_str, "MiB") > 0) {
                gsub(/[^0-9.]/, "", mem_str)
                mem = mem_str
            }

            if (cpu > max_cpu) max_cpu = cpu
            if (mem > max_mem) max_mem = mem
            total_cpu += cpu
            count++
        }
        END {
            if (count > 0) {
                printf "    CPU: Avg %.1f%%, Max %.1f%%\n", total_cpu/count, max_cpu
                printf "    Memory Max: %.0f MiB\n", max_mem
            }
        }'
    done
fi

# Summary and Recommendations
echo -e "\n${GREEN}═══ RECOMMENDATIONS ═══${NC}"

# Check for issues
issues=0

if [[ -f "$LOG_DIR/gpu_metrics.csv" ]]; then
    max_temp=$(tail -n +2 "$LOG_DIR/gpu_metrics.csv" | awk -F',' 'BEGIN{max=0} {if($3>max)max=$3} END{print max}')
    if (( $(echo "$max_temp >= 85" | bc -l) )); then
        echo -e "  ${RED}⚠ CRITICAL: GPU temperature exceeded 85°C - improve cooling or reduce load${NC}"
        issues=$((issues + 1))
    elif (( $(echo "$max_temp >= 80" | bc -l) )); then
        echo -e "  ${YELLOW}⚠ WARNING: GPU temperature exceeded 80°C - monitor closely${NC}"
        issues=$((issues + 1))
    fi
fi

if [[ -f "$LOG_DIR/backend_metrics.csv" ]]; then
    error_count=$(tail -n +2 "$LOG_DIR/backend_metrics.csv" | awk -F',' '$2 != 200 {count++} END{print count+0}')
    if (( error_count > 0 )); then
        echo -e "  ${YELLOW}⚠ Backend had $error_count failed health checks${NC}"
        issues=$((issues + 1))
    fi

    max_latency=$(tail -n +2 "$LOG_DIR/backend_metrics.csv" | awk -F',' 'BEGIN{max=0} {if($3>max)max=$3} END{print max}')
    if (( max_latency > 1000 )); then
        echo -e "  ${YELLOW}⚠ Backend latency exceeded 1000ms (max: ${max_latency}ms)${NC}"
        issues=$((issues + 1))
    fi
fi

if (( issues == 0 )); then
    echo -e "  ${GREEN}✓ No critical issues detected${NC}"
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"

# Generate HTML report
REPORT_FILE="$LOG_DIR/report.html"
cat > "$REPORT_FILE" << 'HTMLEOF'
<!DOCTYPE html>
<html>
<head>
    <title>Load Test Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }
        h1, h2 { color: #00d4ff; }
        .metric { background: #16213e; padding: 20px; border-radius: 8px; margin: 10px 0; }
        .metric h3 { margin-top: 0; color: #00d4ff; }
        .value { font-size: 2em; font-weight: bold; }
        .warning { color: #ffc107; }
        .critical { color: #ff4757; }
        .good { color: #2ed573; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #333; }
        th { background: #0f3460; }
    </style>
</head>
<body>
    <h1>HeartCode Load Test Report</h1>
    <p>Generated: TIMESTAMP</p>
    <div class="metric">
        <h3>Summary</h3>
        <p>Review the CSV files in the log directory for detailed metrics.</p>
    </div>
</body>
</html>
HTMLEOF

# Replace timestamp
sed -i.bak "s/TIMESTAMP/$(date)/" "$REPORT_FILE" && rm -f "$REPORT_FILE.bak"

echo -e "HTML report generated: $REPORT_FILE"
