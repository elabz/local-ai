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

# Check for huggingface-cli
if ! command -v huggingface-cli &> /dev/null; then
  echo "Installing huggingface-hub CLI..."
  pip3 install -q huggingface-hub
fi

download_hf() {
  local repo="$1"
  local file="$2"
  local dest="$3"

  if [ -f "$dest" ]; then
    echo "  [SKIP] $dest already exists"
    return 0
  fi

  echo "  [DOWNLOAD] $repo/$file -> $dest"
  huggingface-cli download "$repo" "$file" --local-dir . --local-dir-use-symlinks False
  # huggingface-cli downloads to subdir, move if needed
  if [ -f "$file" ]; then
    mv "$file" "$dest" 2>/dev/null || true
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
echo "To pre-download, run: huggingface-cli download segmind/SSD-1B SSD-1B.safetensors --local-dir $MODELS_DIR"

echo ""
echo "=== Download Complete ==="
echo ""
ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null || echo "No .gguf files found"
echo ""
echo "Total disk usage:"
du -sh "$MODELS_DIR"
