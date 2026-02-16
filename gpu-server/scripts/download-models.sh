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

# --- Embedding Model ---
echo ""
echo "3/3: Embedding Model (nomic-embed-text-v1.5)"
download_hf "nomic-ai/nomic-embed-text-v1.5-GGUF" "nomic-embed-text-v1.5.Q8_0.gguf" "nomic-embed-text-v1.5.Q8_0.gguf"

# --- Image Model ---
echo ""
echo "Image model (Segmind SSD-1B) will auto-download via LocalAI on first request."

echo ""
echo "=== Download Complete ==="
echo ""
ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null || echo "No .gguf files found"
echo ""
echo "Total disk usage:"
du -sh "$MODELS_DIR"
