#!/bin/bash
# Download all models for the HeartCode PEA GPU server.
#
# Driven by the generated gpu-server/models.download.tsv (the single source of
# truth). To change what gets downloaded, edit gpu-server/models.yaml and
# regenerate:  python3 scripts/render-config.py
#
# Run from anywhere. Options:
#   --fallback-q4   use each gguf's fallback (Q4) file where one is defined
#   --dry-run       print what would be fetched without downloading
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GPU_SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODELS_DIR="$GPU_SERVER_DIR/models"
DOWNLOAD_LIST="$GPU_SERVER_DIR/models.download.tsv"
FALLBACK_Q4=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --fallback-q4) FALLBACK_Q4=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

mkdir -p "$MODELS_DIR"

# download_hf <repo> <file> <dest>
download_hf() {
  local repo="$1" file="$2" dest="$3"
  if [ -f "$dest" ]; then
    echo "  [SKIP] $dest already exists"
    return 0
  fi
  local url="https://huggingface.co/${repo}/resolve/main/${file}"
  if [ "$DRY_RUN" = true ]; then
    echo "  [DRY] would download $url -> $dest"
    return 0
  fi
  echo "  [DOWNLOAD] $url"
  if command -v wget &> /dev/null; then
    wget --progress=bar:force -O "$dest" "$url" || { rm -f "$dest"; return 1; }
  elif command -v curl &> /dev/null; then
    curl -L --progress-bar -o "$dest" "$url" || { rm -f "$dest"; return 1; }
  else
    echo "ERROR: Neither wget nor curl found."; exit 1
  fi
}

# Snapshot a full HF repo into the cache rooted at $MODELS_DIR (HF_HOME=/models at
# runtime, so the transformers embed servers find it offline).
download_hf_snapshot() {
  local repo="$1"
  if [ "$DRY_RUN" = true ]; then
    echo "  [DRY] would snapshot $repo -> $MODELS_DIR (HF cache)"
    return 0
  fi
  export HF_HOME="$MODELS_DIR" HF_HUB_CACHE="$MODELS_DIR"
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

echo "=== HeartCode PEA Model Download ==="
echo "Target: $MODELS_DIR"
echo "List:   $DOWNLOAD_LIST"
[ "$FALLBACK_Q4" = true ] && echo "Mode:   fallback (Q4) where defined"
[ "$DRY_RUN" = true ] && echo "Mode:   dry-run (no downloads)"
echo ""
[ -f "$DOWNLOAD_LIST" ] || { echo "ERROR: $DOWNLOAD_LIST not found — run scripts/render-config.py"; exit 1; }

while IFS=$'\t' read -r kind a b c; do
  [[ -z "${kind:-}" || "$kind" == \#* ]] && continue
  case "$kind" in
    gguf)
      file="$b"
      if [ "$FALLBACK_Q4" = true ] && [ -n "${c:-}" ] && [ "$c" != "-" ]; then
        file="$c"
      fi
      echo "gguf: $a / $file"
      download_hf "$a" "$file" "$MODELS_DIR/$file"
      ;;
    snapshot)
      echo "snapshot: $a"
      download_hf_snapshot "$a"
      ;;
    *)
      echo "  [WARN] unknown row type: $kind" ;;
  esac
done < "$DOWNLOAD_LIST"

echo ""
echo "Image model (Segmind SSD-1B) auto-downloads via LocalAI on first request."
echo ""
echo "=== Download Complete ==="
if [ "$DRY_RUN" != true ]; then
  ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null || echo "No .gguf files found"
  du -sh "$MODELS_DIR"
fi
