#!/bin/bash
# Download embedding model for HeartCode
# Run this on the GPU server before starting embeddings containers

set -e

MODEL_DIR="${1:-./models}"
MODEL_NAME="nomic-embed-text-v1.5.Q8_0.gguf"
MODEL_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"

echo "=== HeartCode Embedding Model Download ==="
echo "Model: $MODEL_NAME"
echo "Target: $MODEL_DIR"
echo ""

# Create models directory if needed
mkdir -p "$MODEL_DIR"

# Check if model already exists
if [ -f "$MODEL_DIR/$MODEL_NAME" ]; then
    echo "Model already exists at $MODEL_DIR/$MODEL_NAME"
    echo "Size: $(du -h "$MODEL_DIR/$MODEL_NAME" | cut -f1)"
    exit 0
fi

# Download model
echo "Downloading from HuggingFace..."
echo "URL: $MODEL_URL"
echo ""

if command -v wget &> /dev/null; then
    wget -O "$MODEL_DIR/$MODEL_NAME" "$MODEL_URL"
elif command -v curl &> /dev/null; then
    curl -L -o "$MODEL_DIR/$MODEL_NAME" "$MODEL_URL"
else
    echo "ERROR: Neither wget nor curl found. Please install one."
    exit 1
fi

echo ""
echo "Download complete!"
echo "Size: $(du -h "$MODEL_DIR/$MODEL_NAME" | cut -f1)"
echo ""
echo "You can now start the embedding servers:"
echo "  docker compose -f docker-compose.ash.yml up -d embedding-server-1 embedding-server-2"
