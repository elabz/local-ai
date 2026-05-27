# Multimodal Embedding Server - nomic-embed-multimodal-3b (BiQwen2.5)
# Target: NVIDIA P104-100 (Pascal, compute capability 6.1 / sm_61), 8GB.
#
# CUDA 12.1 base + torch cu121 wheel — cu121 builds include sm_61, and the
# CUDA-12 PyTorch path is already proven on this no-AVX Celeron host by the
# LocalAI image server. (Validate `import torch` first — openspec task 1.3.)

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Runtime dependencies: python + curl (healthcheck) + git (some pip metadata)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    curl \
    git \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch first (pinned cu121 wheel that ships sm_61), then the rest.
# Keeping torch in its own layer avoids the resolver downgrading it for
# colpali-engine.
RUN pip3 install --upgrade pip && \
    pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Application code
COPY . .

# HF cache / model snapshot root (mounted at runtime)
RUN mkdir -p /models
ENV HF_HOME=/models \
    HF_HUB_CACHE=/models

# Defaults (overridden by docker-compose). These env names map directly to
# config.py fields (no prefix — Settings has no env_prefix).
ENV HOST=0.0.0.0 \
    PORT=8080 \
    METRICS_PORT=9091 \
    PRECISION=float32 \
    ATTN_IMPLEMENTATION=eager \
    MODEL_ID=nomic-ai/nomic-embed-multimodal-3b \
    BASE_MODEL_ID=Qwen/Qwen2.5-VL-3B-Instruct

# /health is 503 until the model is loaded; long start period covers first-run
# base-model download. The watchdog/compose enforce restart on failure.
HEALTHCHECK --interval=30s --timeout=10s --start-period=900s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8080

CMD ["python3", "server.py"]
