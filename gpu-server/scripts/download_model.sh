#!/bin/bash
# Download GGUF models for HeartCode GPU server
# Model to try mlabonne/Daredevil-8B-abliterated
set -e

MODEL_DIR="${MODEL_DIR:-./models}"
mkdir -p "$MODEL_DIR"

echo "Downloading models to $MODEL_DIR..."

# Stheno 8B - Great for roleplay (fits P106-100 with Q4_K_M)
download_stheno() {
    local QUANT="${1:-Q4_K_M}"
    local MODEL_NAME="stheno-l3.1-8b-${QUANT,,}.gguf"
    local URL="https://huggingface.co/Sao10K/L3.1-8B-Stheno-v3.3-GGUF/resolve/main/L3.1-8B-Stheno-v3.3-${QUANT}.gguf"

    if [ -f "$MODEL_DIR/$MODEL_NAME" ]; then
        echo "Model $MODEL_NAME already exists, skipping..."
        return
    fi

    echo "Downloading Stheno L3.1 8B ($QUANT)..."
    wget -O "$MODEL_DIR/$MODEL_NAME" "$URL" || {
        echo "Failed to download $MODEL_NAME"
        return 1
    }
    echo "Downloaded: $MODEL_NAME"
}

# Lumimaid 8B - Another good roleplay model
download_lumimaid() {
    local QUANT="${1:-Q4_K_M}"
    local MODEL_NAME="lumimaid-8b-${QUANT,,}.gguf"
    local URL="https://huggingface.co/NeverSleep/Llama-3.1-Lumimaid-8B-v0.1-GGUF/resolve/main/Llama-3.1-Lumimaid-8B-v0.1-${QUANT}.gguf"

    if [ -f "$MODEL_DIR/$MODEL_NAME" ]; then
        echo "Model $MODEL_NAME already exists, skipping..."
        return
    fi

    echo "Downloading Lumimaid 8B ($QUANT)..."
    wget -O "$MODEL_DIR/$MODEL_NAME" "$URL" || {
        echo "Failed to download $MODEL_NAME"
        return 1
    }
    echo "Downloaded: $MODEL_NAME"
}

# Parse arguments
MODEL="${1:-stheno}"
QUANT="${2:-Q4_K_M}"

case "$MODEL" in
    stheno)
        download_stheno "$QUANT"
        ;;
    lumimaid)
        download_lumimaid "$QUANT"
        ;;
    all)
        echo "Downloading all models..."
        download_stheno "Q4_K_M"
        download_stheno "Q5_K_M"
        download_lumimaid "Q4_K_M"
        ;;
    *)
        echo "Usage: $0 [stheno|lumimaid|all] [quantization]"
        echo ""
        echo "Models:"
        echo "  stheno   - Stheno L3.1 8B (default)"
        echo "  lumimaid - Lumimaid 8B"
        echo "  all      - Download all models"
        echo ""
        echo "Quantizations:"
        echo "  Q4_K_M   - 4-bit (smallest, fits 6GB VRAM) [default]"
        echo "  Q5_K_M   - 5-bit (better quality, needs 8GB VRAM)"
        echo "  Q6_K    - 6-bit (best quality, needs 10GB+ VRAM)"
        exit 1
        ;;
esac

echo ""
echo "Models in $MODEL_DIR:"
ls -lh "$MODEL_DIR"/*.gguf 2>/dev/null || echo "No models found"
