#!/bin/bash
# HeartCode PEA Server - Full Deployment Script
# Run this on pea (192.168.0.144)
#
# Usage:
#   ./setup-pea.sh              # Full setup
#   ./setup-pea.sh --skip-clean # Skip gpustack cleanup
#   ./setup-pea.sh --fallback-q4 # Use Q4_K_M instead of Q5_K_M
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PEA_DIR="$(dirname "$SCRIPT_DIR")"
SKIP_CLEAN=false
FALLBACK_Q4=false

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-clean) SKIP_CLEAN=true; shift ;;
    --fallback-q4) FALLBACK_Q4=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================="
echo "HeartCode PEA Server Setup"
echo "============================================="
echo "Server: $(hostname) ($(hostname -I | awk '{print $1}'))"
echo "Directory: $PEA_DIR"
echo "Skip cleanup: $SKIP_CLEAN"
echo "Fallback Q4: $FALLBACK_Q4"
echo ""

# --- Step 1: Stop gpustack ---
if [ "$SKIP_CLEAN" = false ]; then
  echo "=== Step 1: Stopping gpustack containers ==="
  if docker ps -a --format '{{.Names}}' | grep -q gpustack; then
    echo "Stopping gpustack containers..."
    docker ps -a --format '{{.Names}}' | grep gpustack | xargs -r docker stop
    docker ps -a --format '{{.Names}}' | grep gpustack | xargs -r docker rm
    echo "gpustack containers removed."
  else
    echo "No gpustack containers found."
  fi

  echo ""
  echo "=== Step 2: Docker cleanup ==="
  echo "Pruning unused images and volumes..."
  docker system prune -f
  docker volume prune -f
  echo ""
  echo "Disk space after cleanup:"
  df -h / | tail -1
else
  echo "=== Skipping cleanup (--skip-clean) ==="
fi

# --- Step 3: Download models ---
echo ""
echo "=== Step 3: Download models ==="
DOWNLOAD_ARGS=""
if [ "$FALLBACK_Q4" = true ]; then
  DOWNLOAD_ARGS="--fallback-q4"
fi
bash "$SCRIPT_DIR/download-models.sh" $DOWNLOAD_ARGS

# --- Step 4: Build Docker image ---
echo ""
echo "=== Step 4: Building Docker image ==="
cd "$PEA_DIR"
docker compose build

# --- Step 5: Start services in stages ---
echo ""
echo "=== Step 5: Starting services ==="

echo "Starting chat servers..."
docker compose up -d gpu-server-1 gpu-server-2 gpu-server-3 gpu-server-4 gpu-server-5 gpu-server-6 gpu-server-7
echo "Waiting 30s for chat servers to initialize..."
sleep 30

echo "Starting embedding servers..."
docker compose up -d embedding-server-1 embedding-server-2 embedding-server-3 embedding-server-4 embedding-server-5 embedding-server-6 embedding-server-7
echo "Waiting 15s for embedding servers to initialize..."
sleep 15

echo "Starting image server..."
docker compose up -d image-server
echo "Waiting 30s for image server to initialize..."
sleep 30

echo "Starting monitoring..."
docker compose up -d prometheus node-exporter dcgm-exporter

# --- Step 6: Health checks ---
echo ""
echo "=== Step 6: Health Checks ==="
echo ""

check_health() {
  local name="$1"
  local url="$2"
  local status
  status=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    echo "  [OK]   $name ($url)"
  else
    echo "  [FAIL] $name ($url) - HTTP $status"
  fi
}

echo "Chat servers:"
for i in $(seq 0 6); do
  port=$((8080 + i))
  check_health "GPU $i (chat)" "http://localhost:$port/health"
done

echo ""
echo "Embedding servers:"
for i in $(seq 0 6); do
  port=$((8090 + i))
  check_health "GPU $i (embed)" "http://localhost:$port/health"
done

echo ""
echo "Image server:"
check_health "GPU 7 (image)" "http://localhost:5100/readyz"

echo ""
echo "Monitoring:"
check_health "Prometheus" "http://localhost:9090/-/ready"
check_health "Node Exporter" "http://localhost:9100/metrics"
check_health "DCGM Exporter" "http://localhost:9400/metrics"

# --- Summary ---
echo ""
echo "============================================="
echo "PEA Server Setup Complete"
echo "============================================="
echo ""
echo "Services:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
echo ""
echo "GPU Memory Usage:"
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "nvidia-smi not available"
echo ""
echo "Next steps:"
echo "  1. Test chat:  curl http://192.168.0.144:8080/v1/chat/completions -d '{\"model\":\"model\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":50}'"
echo "  2. Test embed: curl http://192.168.0.144:8090/v1/embeddings -d '{\"model\":\"model\",\"input\":\"test\"}'"
echo "  3. Test image: curl http://192.168.0.144:5100/v1/images/generations -d '{\"prompt\":\"sunset\",\"model\":\"heartcode-image\",\"size\":\"512x512\"}'"
echo "  4. Start LiteLLM proxy locally to test routing"
