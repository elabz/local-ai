# Local AI

Shared GPU inference infrastructure for local network projects. Provides OpenAI-compatible API endpoints for chat completion, embeddings, and image generation.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PEA Server (192.168.0.144) - gpu-server/                    │
│                                                              │
│  GPU 1-3: llama.cpp SFW chat     (ports 8080-8082)          │
│  GPU 4-7: llama.cpp NSFW chat    (ports 8083-8086)          │
│  GPU 1-7: llama.cpp embeddings   (ports 8090-8096)          │
│  GPU 8:   LocalAI image gen      (port 5100)                │
│  8x NVIDIA P104-100 (8GB VRAM each), 32GB RAM               │
└───────────────────────┬──────────────────────────────────────┘
                        │ LAN
┌───────────────────────▼──────────────────────────────────────┐
│  Prod Server (192.168.0.152) - litellm/                      │
│                                                              │
│  LiteLLM Proxy      (port 4000)  ──→ PEA:8080-8096,5100    │
│  PostgreSQL          (port 5432)  (API key storage)          │
│  Langfuse            (port 3002)  (LLM observability)        │
│  Prometheus/Grafana  (ports 9090/3001)                       │
└───────────────────────┬──────────────────────────────────────┘
                        │ LAN
│  Clients: Any project on the network                         │
│  → http://192.168.0.152:4000/v1/chat/completions             │
│  → http://192.168.0.152:4000/v1/embeddings                   │
│  → http://192.168.0.152:4000/v1/images/generations           │
```

## Components

| Directory | Description | Deployed On |
|-----------|-------------|-------------|
| `gpu-server/` | llama.cpp + LocalAI inference servers (8x GPU) | PEA (192.168.0.144) |
| `litellm/` | LiteLLM proxy + PostgreSQL for API keys | Prod (192.168.0.152) |
| `monitoring/` | Prometheus + Grafana dashboards | Prod (192.168.0.152) |
| `langfuse/` | LLM observability and tracing | Prod (192.168.0.152) |
| `load-tests/` | k6 stress tests and analysis tools | Dev machine |

## Models

| API Name | Type | GPUs | Model | Quantization |
|----------|------|------|-------|--------------|
| `heartcode-chat-sfw` | Chat | 1-3 (3x P104-100) | Llama-3.1-8B-Stheno-v3.4 | Q5_K_M |
| `heartcode-chat-nsfw` | Chat | 4-7 (4x P104-100) | Lumimaid-v0.2-8B (NeverSleep) | Q5_K_M |
| `heartcode-embed` | Embedding | 1-7 (7x P104-100) | nomic-embed-text-v1.5 | Q8_0 |
| `heartcode-image` | Image | 8 (1x P104-100) | Segmind SSD-1B (SDXL distilled) | FP16 |

**Aliases:** `heartcode-chat` and `heartcode-default` → `heartcode-chat-sfw`, `heartcode-sfw` → `heartcode-chat-sfw`, `heartcode-nsfw` → `heartcode-chat-nsfw`

## Quick Start

### 1. GPU Servers (PEA)

```bash
cd gpu-server
cp .env.example .env         # Configure model paths per GPU
docker build -t local-ai-llama:latest .
./scripts/download-models.sh  # Download GGUF models from HuggingFace
docker compose up -d          # Start all servers
```

### 2. LiteLLM Proxy (Prod Server)

```bash
cd litellm
cp .env.example .env    # Set LITELLM_MASTER_KEY and LITELLM_DB_PASSWORD
docker compose up -d    # Start LiteLLM + PostgreSQL
```

### 3. Generate an API Key

```bash
curl -X POST http://192.168.0.152:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"models": ["heartcode-chat-sfw", "heartcode-chat-nsfw", "heartcode-embed", "heartcode-image"],
       "key_alias": "my-project"}'
```

### 4. Use the API

```bash
# Chat completion (SFW)
curl http://192.168.0.152:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-chat-sfw",
       "messages": [{"role": "user", "content": "Hello!"}],
       "max_tokens": 256}'

# Chat completion (NSFW)
curl http://192.168.0.152:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-chat-nsfw",
       "messages": [{"role": "user", "content": "Hello!"}],
       "max_tokens": 256}'

# Embeddings
curl http://192.168.0.152:4000/v1/embeddings \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-embed",
       "input": "Text to embed"}'

# Image generation (~48s per 512x512 image)
curl http://192.168.0.152:4000/v1/images/generations \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "heartcode-image",
       "prompt": "a cute anime girl avatar, portrait, fantasy style",
       "size": "512x512"}'
```

## Performance

| Model | Metric | Value |
|-------|--------|-------|
| SFW Chat | Throughput | ~35 RPM across 3 GPUs |
| NSFW Chat | Throughput | ~45 RPM across 4 GPUs |
| Embeddings | Throughput | High (lightweight model) |
| Image Gen | Latency | ~48s per 512x512 image (20 steps) |

## API Key Management

LiteLLM uses PostgreSQL-backed virtual keys. Manage via the master key:

```bash
# Create key with model restrictions and rate limits
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models": ["heartcode-chat-sfw", "heartcode-embed"],
       "rpm_limit": 30,
       "key_alias": "project-name"}'

# List keys
curl http://localhost:4000/key/info \
  -H "Authorization: Bearer $MASTER_KEY"

# Delete key
curl -X POST http://localhost:4000/key/delete \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"keys": ["sk-key-to-delete"]}'
```

## Hardware

### PEA (192.168.0.144) - GPU Server
- **CPU**: Intel Celeron 3865U (2-core, no AVX)
- **RAM**: 32GB DDR4
- **GPUs**: 8x NVIDIA P104-100 (8GB VRAM, Pascal, compute 6.1)
- **Power**: 90W limit per GPU via `nvidia-power-limit.service`

### Prod (192.168.0.152) - Proxy Server
- Runs LiteLLM proxy, PostgreSQL, monitoring stack
- No GPU required

## Monitoring

```bash
# Prometheus (on PEA): http://192.168.0.144:9099
# Start monitoring stack on Prod:
cd monitoring
docker compose up -d
# Grafana: http://192.168.0.152:3001
# Prometheus: http://192.168.0.152:9090
```

## Load Testing

```bash
cd load-tests
k6 run -e API_KEY=$YOUR_KEY stress-all-gpus.js
```

See `docs/load-test-findings.md` for capacity analysis and safe operating limits.

## Setup Guide

See `docs/pea-server-setup.md` for comprehensive instructions on setting up a GPU server from scratch.
