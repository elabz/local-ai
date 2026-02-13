# CLAUDE.md

## Project Overview

Local AI is a shared GPU inference infrastructure for local network projects. It provides OpenAI-compatible API endpoints via LiteLLM proxy, backed by llama.cpp GPU servers.

## Repository Structure

```
local-ai/
├── gpu-server/           # llama.cpp inference servers (PEA - primary)
│   ├── docker-compose.yml  # 7 chat + 7 embed + 1 image + monitoring
│   ├── server.py           # FastAPI wrapper with metrics
│   ├── Dockerfile          # CUDA build for Pascal GPUs
│   ├── configs/            # prometheus.yml, entrypoint-wrapper.sh, etc.
│   ├── scripts/            # setup-pea.sh, download-models.sh, watchdog, diagnostics
│   └── models/             # .gitkeep + heartcode-image.yaml (GGUF files excluded)
├── litellm/              # LiteLLM proxy + PostgreSQL API key management
│   ├── docker-compose.yml  # LiteLLM + PostgreSQL
│   ├── config.yaml         # Production config (model routing, rate limits)
│   └── config-local.yaml   # Local dev config
├── gpu-image-server/     # Stable Diffusion (2x RTX 3070)
│   └── docker-compose.yml
├── monitoring/           # Prometheus + Grafana + AlertManager
│   ├── prometheus/
│   └── grafana/
├── langfuse/             # LLM observability
│   └── docker-compose.yml
├── load-tests/           # k6 stress tests
│   ├── stress-all-gpus.js
│   └── monitor.sh
└── docs/                 # Documentation
```

## Deployment Topology

- **PEA (192.168.0.144)**: All GPU servers — 3 SFW + 4 NSFW + 7 embed + 1 image - `gpu-server/docker-compose.yml`
- **Prod (192.168.0.152)**: LiteLLM proxy + monitoring - `litellm/docker-compose.yml`
- **Image (192.168.0.143)**: Legacy Stable Diffusion - `gpu-image-server/docker-compose.yml`

## Common Commands

### GPU Server (on PEA)
```bash
cd gpu-server
docker compose up -d                    # Start all GPU servers
docker compose ps                       # Check health
docker compose logs -f pea-gpu-1        # View specific GPU logs
docker compose restart gpu-server-1     # Restart one server
./scripts/setup-pea.sh                  # Full deployment from scratch
```

### LiteLLM Proxy (on Prod)
```bash
cd litellm
docker compose up -d                    # Start LiteLLM + PostgreSQL
docker compose logs -f litellm          # View proxy logs
curl http://localhost:4000/health       # Health check

# API Key Management
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models":["heartcode-chat-sfw"],"key_alias":"test"}'
```

### Load Testing
```bash
cd load-tests
k6 run -e API_KEY=$KEY stress-all-gpus.js
./monitor.sh                            # Real-time monitoring
```

## Model Names

- `heartcode-chat-sfw` - SFW chat (PEA GPU 1-3, Stheno v3.4 8B Q5_K_M)
- `heartcode-chat-nsfw` - NSFW chat (PEA GPU 4-7, Lumimaid v0.2 8B Q5_K_M)
- `heartcode-chat` - Alias for heartcode-chat-sfw
- `heartcode-embed` - Embeddings (PEA GPU 1-7, nomic-embed-text-v1.5)
- `heartcode-image` - Image generation (PEA GPU 8, Segmind SSD-1B)

## Key Configuration

### LiteLLM Config (`litellm/config.yaml`)
- Model routing and GPU server endpoints
- Rate limits: 45 RPM per model group
- Health checks every 15s, 2 allowed fails before cooldown
- Max 8-16 parallel requests (depends on config)

### GPU Server Config (`gpu-server/docker-compose.yml`)
- Memory limit: 2048m per chat server
- N_GPU_LAYERS=33, N_CTX=16384, N_BATCH=128, N_UBATCH=64
- KV cache: q8_0 quantization
- Power limit: 90W per GPU (nvidia-power-limit.service)

## Hardware Constraints

### PEA (primary)
- **CPUs**: 2-core Celeron 3865U (no AVX) - needs special llama.cpp build flags
- **GPUs**: 8x P104-100 (8GB VRAM, Pascal architecture, compute 6.1)
- **RAM**: 32GB
- **Safe limits**: 35 RPM SFW (3 GPUs), 45 RPM NSFW (4 GPUs)
