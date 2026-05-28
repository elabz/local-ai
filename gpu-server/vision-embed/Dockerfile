# Vision Embedding Server — nomic-embed-vision-v1.5 + nomic-embed-text-v1.5.
# Target: NVIDIA P104-100 (Pascal, sm_61), 8GB. CUDA 12.1 base + torch cu121
# (ships sm_61), proven on this no-AVX Celeron host by the multimodal-embed and
# LocalAI image servers.

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    curl \
    git \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch + torchvision first (pinned cu121 wheels that ship sm_61).
RUN pip3 install --upgrade pip && \
    pip3 install torch==2.4.1 torchvision==0.19.1 \
        --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY . .

RUN mkdir -p /models
ENV HF_HOME=/models \
    HF_HUB_CACHE=/models

# These env names map directly to config.py fields (no prefix).
ENV HOST=0.0.0.0 \
    PORT=8080 \
    METRICS_PORT=9091 \
    PRECISION=float32 \
    VISION_MODEL_ID=nomic-ai/nomic-embed-vision-v1.5 \
    TEXT_MODEL_ID=nomic-ai/nomic-embed-text-v1.5

# /health is 503 until both towers load; first run may download the snapshots.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8080

CMD ["python3", "server.py"]
