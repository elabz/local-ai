#!/bin/bash
#
# GPU Server Diagnostics
# Run on ASH to capture NVIDIA Device UUIDs and check watchdog service status
#
# Usage:
#   sudo ./gpu-diagnostics.sh
#

set -euo pipefail

echo "=================================================="
echo "HeartCode GPU Server Diagnostics"
echo "=================================================="
echo ""

# 1. NVIDIA Device Information
echo "=== NVIDIA Device Information ==="
echo ""
if command -v nvidia-smi &> /dev/null; then
    echo "GPU UUIDs (indexed 0-7):"
    nvidia-smi --query-gpu=index,uuid,name,driver_version --format=csv 2>/dev/null || echo "ERROR: Could not query nvidia-smi"
    echo ""
else
    echo "ERROR: nvidia-smi not found"
fi

# 2. GPU Watchdog Service Status
echo "=== GPU Watchdog Service Status ==="
echo ""
if systemctl list-unit-files | grep -q gpu-watchdog; then
    echo "Service: gpu-watchdog"
    systemctl status gpu-watchdog.service --no-pager 2>/dev/null || echo "Service exists but status check failed"
    echo ""
    echo "Recent watchdog logs:"
    journalctl -u gpu-watchdog.service -n 20 --no-pager 2>/dev/null || echo "No systemd logs available"
    echo ""
else
    echo "ERROR: gpu-watchdog.service not installed"
    echo "To install, run: sudo /home/boss/heartcode/gpu-server/scripts/install-watchdog.sh"
    echo ""
fi

# 3. GPU VRAM Status (for each GPU)
echo "=== Current GPU VRAM Status ==="
echo ""
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=index,memory.used,memory.total,name --format=csv 2>/dev/null || echo "ERROR: Could not query VRAM"
    echo ""
else
    echo "ERROR: nvidia-smi not found"
fi

# 4. Docker Container Status
echo "=== Docker Container Status ==="
echo ""
echo "GPU Server Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "gpu-server|gpu-[0-9]" || echo "No GPU containers running"
echo ""
echo "Embedding Server Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "embed-server|embed-[0-9]" || echo "No embedding containers running"
echo ""

# 5. LiteLLM Proxy Status
echo "=== LiteLLM Proxy Status ==="
echo ""
docker ps --format "table {{.Names}}\t{{.Status}}" | grep litellm || echo "LiteLLM container not running"
echo ""

# 6. GPU 5 Specific Diagnostics
echo "=== GPU 5 (NVIDIA Device 4) - Detailed Status ==="
echo ""
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi -i 4 --query-gpu=index,uuid,name,temperature.gpu,memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null || echo "ERROR: Could not query GPU 5"
    echo ""
else
    echo "ERROR: nvidia-smi not found"
fi

echo "Container Status for GPU 5:"
docker inspect local-ai-gpu-5 --format='{{.Name}}: {{.State.Status}}' 2>/dev/null || echo "Container local-ai-gpu-5 not found"
docker inspect local-ai-embed-5 --format='{{.Name}}: {{.State.Status}}' 2>/dev/null || echo "Container local-ai-embed-5 not found"
echo ""

echo "=================================================="
echo "Diagnostics Complete"
echo "=================================================="
