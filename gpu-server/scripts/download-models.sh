#!/bin/bash
# Download all models for HeartCode PEA GPU server
# Run from gpu-server/ directory
set -euo pipefail

MODELS_DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
FALLBACK_Q4=false

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --fallback-q4) FALLBACK_Q4=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

echo "=== HeartCode PEA Model Download ==="
echo "Target directory: $MODELS_DIR"
echo ""

# Download a file from HuggingFace using wget or curl
download_hf() {
  local repo="$1"
  local file="$2"
  local dest="$3"

  if [ -f "$dest" ]; then
    echo "  [SKIP] $dest already exists"
    return 0
  fi

  local url="https://huggingface.co/${repo}/resolve/main/${file}"
  echo "  [DOWNLOAD] $url"

  if command -v wget &> /dev/null; then
    wget --progress=bar:force -O "$dest" "$url" || { rm -f "$dest"; return 1; }
  elif command -v curl &> /dev/null; then
    curl -L --progress-bar -o "$dest" "$url" || { rm -f "$dest"; return 1; }
  else
    echo "ERROR: Neither wget nor curl found."
    exit 1
  fi
}

# Snapshot a full HuggingFace repo into the HF cache rooted at $MODELS_DIR. The
# multimodal-embed container runs with HF_HOME=/models, so a cache built here is
# found offline at runtime (no first-request download).
download_hf_snapshot() {
  local repo="$1"
  export HF_HOME="$MODELS_DIR"
  export HF_HUB_CACHE="$MODELS_DIR"
  echo "  [SNAPSHOT] $repo -> $MODELS_DIR (HF cache)"

  if command -v huggingface-cli &> /dev/null; then
    huggingface-cli download "$repo" >/dev/null || return 1
  elif python3 -c "import huggingface_hub" &> /dev/null; then
    python3 - "$repo" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1])
PY
  else
    echo "  ERROR: huggingface_hub not found. Install with: pip install -U 'huggingface_hub[cli]'"
    return 1
  fi
}

# --- SFW Chat Model ---
echo ""
echo "1/3: SFW Chat Model (Stheno v3.4 8B)"
if [ "$FALLBACK_Q4" = true ]; then
  echo "  Using Q4_K_M (fallback mode)"
  download_hf "bartowski/Llama-3.1-8B-Stheno-v3.4-GGUF" "Llama-3.1-8B-Stheno-v3.4-Q4_K_M.gguf" "Llama-3.1-8B-Stheno-v3.4-Q4_K_M.gguf"
else
  echo "  Using Q5_K_M"
  download_hf "bartowski/Llama-3.1-8B-Stheno-v3.4-GGUF" "Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf" "Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf"
fi

# --- NSFW Chat Model ---
echo ""
echo "2/3: NSFW Chat Model (Lumimaid v0.2 8B)"
if [ "$FALLBACK_Q4" = true ]; then
  echo "  Using Q4_K_M (fallback mode)"
  download_hf "Lewdiculous/Lumimaid-v0.2-8B-GGUF-IQ-Imatrix" "Lumimaid-v0.2-8B-Q4_K_M-imat.gguf" "Lumimaid-v0.2-8B-Q4_K_M-imat.gguf"
else
  echo "  Using Q5_K_M (imatrix)"
  download_hf "Lewdiculous/Lumimaid-v0.2-8B-GGUF-IQ-Imatrix" "Lumimaid-v0.2-8B-Q5_K_M-imat.gguf" "Lumimaid-v0.2-8B-Q5_K_M-imat.gguf"
fi

# --- Embedding Models (all Apache-2.0) ---
echo ""
echo "3/3: Embedding models"
echo "  - nomic-embed-vision-v1.5 + nomic-embed-text-v1.5 (vision-embed, shared 768-d)"
echo "  - facebook/dinov2-with-registers-large (dino-embed, visual similarity, 1024-d)"
download_hf_snapshot "nomic-ai/nomic-embed-vision-v1.5"
download_hf_snapshot "nomic-ai/nomic-embed-text-v1.5"
download_hf_snapshot "facebook/dinov2-with-registers-large"
# (Shelved BiQwen2.5 models — nomic-embed-multimodal-3b + Qwen2.5-VL-3B — are no
#  longer downloaded; restore from change switch-to-nomic-multimodal-embed if revived.)

# --- Image Model ---
echo ""
echo "Image model (Segmind SSD-1B) will auto-download via LocalAI on first request."

echo ""
echo "=== Download Complete ==="
echo ""
ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null || echo "No .gguf files found"
echo ""
echo "HF snapshots (multimodal embed):"
ls -d "$MODELS_DIR"/hub/models--* 2>/dev/null || echo "  (none — multimodal embed not snapshotted)"
echo ""
echo "Total disk usage:"
du -sh "$MODELS_DIR"
