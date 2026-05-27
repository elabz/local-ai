# Image-search service — lightweight, CPU-only (no GPU/ML stack).
# Embeddings come from the heartcode-embed HTTP endpoint; storage from ES REST.

FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# These env names map directly to config.py fields (no prefix). Override in
# docker-compose. EMBED_DIM defaults to 768 (nomic-embed-vision-v1.5).
ENV HOST=0.0.0.0 \
    PORT=8200 \
    METRICS_PORT=9091 \
    EMBED_DIM=768

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8200

CMD ["python3", "server.py"]
