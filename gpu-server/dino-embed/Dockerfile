# DINOv2 Visual Embedding Server — facebook/dinov2-with-registers-large.
# Target: NVIDIA P104-100 (Pascal, sm_61), 8GB. CUDA 12.1 + torch cu121 (sm_61),
# same proven base as vision-embed. DINOv2 is native in transformers (no
# trust_remote_code).

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

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
    MODEL_ID=facebook/dinov2-with-registers-large

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8080

CMD ["python3", "server.py"]
