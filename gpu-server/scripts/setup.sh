#!/bin/bash
# Setup script for HeartCode GPU Server

set -e

echo "=== HeartCode GPU Server Setup ==="
echo ""

# Create directories
echo "Creating directories..."
mkdir -p models
mkdir -p configs

# Check if model exists
if [ ! -f "models/model.gguf" ]; then
    echo ""
    echo "Model file not found at models/model.gguf"
    echo ""
    echo "You need to download a GGUF model file and place it in the models/ directory."
    echo ""
    echo "Recommended models for Pascal GPUs (6-8GB VRAM):"
    echo "  - Llama 3.2 3B Q4_K_M (https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF)"
    echo "  - Mistral 7B Q4_K_M (https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF)"
    echo "  - Phi-3 Mini Q5_K_M (https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf)"
    echo ""
    echo "Example download command:"
    echo "  cd models"
    echo "  wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf -O model.gguf"
    echo ""
    echo "Or use huggingface-cli:"
    echo "  pip install huggingface_hub"
    echo "  huggingface-cli download bartowski/Llama-3.2-3B-Instruct-GGUF Llama-3.2-3B-Instruct-Q4_K_M.gguf --local-dir models --local-dir-use-symlinks False"
    echo "  mv models/Llama-3.2-3B-Instruct-Q4_K_M.gguf models/model.gguf"
    echo ""
    exit 1
else
    echo "Model file found: models/model.gguf"
    MODEL_SIZE=$(du -h models/model.gguf | cut -f1)
    echo "Model size: $MODEL_SIZE"
fi

# Check GPU availability
echo ""
echo "Checking GPU availability..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
    GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader | head -1)
    echo ""
    echo "Found $GPU_COUNT GPU(s)"
else
    echo "WARNING: nvidia-smi not found. Make sure NVIDIA drivers are installed."
fi

# Check Docker
echo ""
echo "Checking Docker..."
if command -v docker &> /dev/null; then
    docker --version
else
    echo "ERROR: Docker not found. Please install Docker first."
    exit 1
fi

# Check nvidia-docker
echo ""
echo "Checking NVIDIA Docker runtime..."
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo "NVIDIA Docker runtime is working"
else
    echo "WARNING: NVIDIA Docker runtime test failed. Make sure nvidia-docker2 is installed."
    echo "Install with: sudo apt-get install nvidia-docker2"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Review docker-compose.yml and adjust GPU assignments if needed"
echo "  2. Start the services: docker compose up -d"
echo "  3. Check logs: docker compose logs -f"
echo "  4. Access LiteLLM proxy at: http://localhost:4000"
echo "  5. Access Prometheus at: http://localhost:9090"
echo ""
