# CLAUDE.md

## Project Overview

Local AI is a shared GPU inference infrastructure for local network projects. It provides OpenAI-compatible API endpoints via LiteLLM proxy, backed by llama.cpp GPU servers.

## Repository Structure

```
local-ai/
├── gpu-server/           # llama.cpp inference (8x P106-100 GPUs on ASH)
│   ├── docker-compose.yml  # 8 chat + 8 embed servers
│   ├── server.py           # FastAPI wrapper with metrics
│   ├── Dockerfile          # CUDA build for Pascal GPUs
│   └── scripts/            # Watchdog, diagnostics, model download
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

- **ASH (192.168.0.145)**: GPU servers - `gpu-server/docker-compose.yml`
- **Prod (192.168.0.152)**: LiteLLM proxy + monitoring - `litellm/docker-compose.yml`
- **Image (192.168.0.143)**: Stable Diffusion - `gpu-image-server/docker-compose.yml`

## Common Commands

### GPU Server (on ASH)
```bash
cd gpu-server
docker compose up -d                    # Start all GPU servers
docker compose ps                       # Check health
docker compose logs -f gpu-sfw-1        # View specific GPU logs
docker compose restart gpu-sfw-1        # Restart one server
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
  -d '{"models":["local-ai-chat-sfw"],"key_alias":"test"}'
```

### Load Testing
```bash
cd load-tests
k6 run -e API_KEY=$KEY stress-all-gpus.js
./monitor.sh                            # Real-time monitoring
```

## Model Names

- `local-ai-chat-sfw` - SFW chat (GPUs 1-4, Stheno-L3.1-8B)
- `local-ai-chat-nsfw` - NSFW chat (GPUs 5-8, Lumimaid-v0.2-8B)
- `local-ai-chat` - Alias for local-ai-chat-sfw
- `local-ai-embed` - Embeddings (GPUs 1-8, nomic-embed-text-v1.5)

## Key Configuration

### LiteLLM Config (`litellm/config.yaml`)
- Model routing and GPU server endpoints
- Rate limits: 45 RPM per model group
- Health checks every 15s, 2 allowed fails before cooldown
- Max 8-16 parallel requests (depends on config)

### GPU Server Config (`gpu-server/docker-compose.yml`)
- Memory limit: 3072m per chat server
- N_GPU_LAYERS=33, N_BATCH=128, N_UBATCH=64
- KV cache: q8_0 quantization
- Power limit: 90W per GPU (nvidia-power-limit.service)

## Hardware Constraints

- **CPUs**: 2-core Celeron (no AVX) - needs special llama.cpp build flags
- **GPUs**: 8x P106-100 (6GB VRAM, Pascal architecture)
- **RAM**: 32GB (upgraded from 16GB)
- **Safe limits**: 30 RPM confirmed, 45 RPM testing
