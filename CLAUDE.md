# CLAUDE.md

## Project Overview

Local AI is a shared GPU inference infrastructure for local network projects. It provides OpenAI-compatible API endpoints via LiteLLM proxy, backed by llama.cpp GPU servers and LocalAI for image generation.

## Repository Structure

```
local-ai/
├── gpu-server/           # llama.cpp + LocalAI inference servers (PEA)
│   ├── docker-compose.yml  # 7 chat + 7 embed + 1 image + monitoring
│   ├── server.py           # FastAPI wrapper with metrics
│   ├── llama_client.py     # Async client proxying to llama.cpp native API
│   ├── routes.py           # OpenAI-compatible API routes
│   ├── config.py           # Pydantic settings from env vars
│   ├── metrics.py          # Prometheus metrics collection
│   ├── Dockerfile          # CUDA build for Pascal GPUs (no AVX)
│   ├── configs/            # prometheus.yml, entrypoint-wrapper.sh
│   ├── scripts/            # setup-pea.sh, download-models.sh, watchdog, diagnostics
│   └── models/             # heartcode-image.yaml (GGUF files excluded via .gitignore)
├── litellm/              # LiteLLM proxy + PostgreSQL API key management
│   ├── docker-compose.yml  # LiteLLM + PostgreSQL
│   ├── config.yaml         # Production config (model routing, rate limits)
│   └── config-local.yaml   # Local dev config
├── monitoring/           # Prometheus + Grafana + AlertManager
│   ├── prometheus/
│   └── grafana/
├── langfuse/             # LLM observability
│   └── docker-compose.yml
├── load-tests/           # k6 stress tests
│   ├── stress-all-gpus.js
│   └── monitor.sh
└── docs/                 # Documentation
    ├── pea-server-setup.md   # Comprehensive setup guide
    └── load-test-findings.md # Capacity analysis
```

## Deployment Topology

- **PEA (192.168.0.144)**: All GPU servers — 3 SFW + 4 NSFW + 7 embed + 1 image — `gpu-server/docker-compose.yml`
- **Prod (192.168.0.152)**: LiteLLM proxy + monitoring — `litellm/docker-compose.yml`

## Common Commands

### GPU Server (on PEA - 192.168.0.144)
```bash
cd gpu-server
docker compose up -d                    # Start all GPU servers
docker compose ps                       # Check health (17 containers)
docker compose logs -f pea-gpu-1        # View specific GPU logs
docker compose restart gpu-server-1     # Restart one server
docker build -t local-ai-llama:latest . # Rebuild llama.cpp image
./scripts/setup-pea.sh                  # Full deployment from scratch
./scripts/download-models.sh            # Download all GGUF models
```

### LiteLLM Proxy (on Prod - 192.168.0.152)
```bash
cd litellm
docker compose up -d                    # Start LiteLLM + PostgreSQL
docker compose logs -f litellm          # View proxy logs
docker compose restart litellm          # Restart after config changes

# API Key Management
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models":["heartcode-chat-sfw","heartcode-chat-nsfw","heartcode-embed","heartcode-image"],"key_alias":"test"}'
```

### Load Testing
```bash
cd load-tests
k6 run -e API_KEY=$KEY stress-all-gpus.js
./monitor.sh                            # Real-time monitoring
```

## Models

| API Name | Type | GPUs | Model | Quant | Chat Template |
|----------|------|------|-------|-------|---------------|
| `heartcode-chat-sfw` | Chat | 1-3 | Llama-3.1-8B-Stheno-v3.4 | Q5_K_M | Llama3 |
| `heartcode-chat-nsfw` | Chat | 4-7 | Lumimaid-v0.2-8B (NeverSleep) | Q5_K_M | Llama3 |
| `heartcode-embed` | Embedding | 1-7 | nomic-embed-text-v1.5 | Q8_0 | — |
| `heartcode-image` | Image | 8 | Segmind SSD-1B (SDXL distilled) | FP16 | — |

**Aliases**: `heartcode-default`, `heartcode-sfw`, `heartcode-chat` → `heartcode-chat-sfw` | `heartcode-nsfw` → `heartcode-chat-nsfw`

## Port Layout (PEA)

| Ports | Service | GPU |
|-------|---------|-----|
| 8080-8082 | SFW chat servers | GPU 1-3 |
| 8083-8086 | NSFW chat servers | GPU 4-7 |
| 8090-8096 | Embedding servers | GPU 1-7 |
| 5100 | Image generation (LocalAI) | GPU 8 |
| 9099 | Prometheus | — |
| 9100 | Node Exporter | — |

## Key Configuration

### GPU Server (`gpu-server/docker-compose.yml`)
- Memory limit: 2048m per chat server, 512m per embed server, 4096m for image server
- `N_GPU_LAYERS=33`, `N_CTX=16384`, `N_BATCH=128`, `N_UBATCH=64`, `N_THREADS=2`
- KV cache: `q8_0` quantization for both keys and values
- `EXTRA_ARGS: "--jinja"` — enables Jinja chat templates for Llama 3.1 models
- `CACHE_REUSE=256` — prompt caching for faster TTFT
- Power limit: 90W per GPU (`nvidia-power-limit.service`)

### LiteLLM Config (`litellm/config.yaml`)
- All endpoints point to PEA (192.168.0.144)
- Routing: `least-busy` strategy with 2 retries
- Rate limits: 35 RPM SFW (3 GPUs), 45 RPM NSFW (4 GPUs)
- Health checks every 15s, 2 allowed fails before 60s cooldown
- Max 7 parallel requests per model, 14 global

### Image Server (`gpu-server/models/heartcode-image.yaml`)
- Backend: `diffusers` (auto-installed from LocalAI gallery on first start)
- Pipeline: `StableDiffusionXLPipeline` with `k_dpmpp_2m` scheduler
- Persistent backend volume: `image_backends` mounted at `/backends`
- Generation time: ~48s per 512x512 image

## Architecture Notes

### FastAPI Wrapper (server.py)
The GPU chat servers use a FastAPI wrapper around llama.cpp's `llama-server`:
- `server.py` manages the llama-server subprocess lifecycle
- `llama_client.py` proxies `/v1/chat/completions` directly to llama-server's native OpenAI-compatible endpoint (llama-server handles chat template conversion via `--jinja`)
- `routes.py` adds Prometheus metrics and request tracking
- `config.py` reads settings from environment variables (Pydantic)

### Dockerfile Build
- Base: `nvidia/cuda:11.8.0-devel-ubuntu22.04` (builder), `runtime` (final)
- Builds llama.cpp from latest `main` branch with CUDA for compute 6.1
- Special flags for no-AVX CPUs: `-march=x86-64 -mno-bmi2`, all AVX/FMA/F16C disabled

### LocalAI Image Server
- Uses `localai/localai:latest-gpu-nvidia-cuda-12` image
- `entrypoint-wrapper.sh` auto-installs `cuda12-diffusers` backend from gallery on first start (~7.4GB download)
- Backend persisted in Docker volume across restarts
- Model (`segmind/SSD-1B`) auto-downloads from HuggingFace on first request

## Hardware

### PEA (192.168.0.144)
- **CPU**: Intel Celeron 3865U (2-core, 1.8GHz, no AVX/AVX2/BMI2)
- **RAM**: 32GB DDR4
- **GPUs**: 8x P104-100 (8GB VRAM, Pascal, compute 6.1)
- **GPU numbering**: 1-indexed in configs (GPU 1-8), 0-indexed physical (`NVIDIA_VISIBLE_DEVICES=0-7`)
- **Safe limits**: 35 RPM SFW (3 GPUs), 45 RPM NSFW (4 GPUs)

### Prod (192.168.0.152)
- Runs LiteLLM proxy, PostgreSQL, optional monitoring stack
- No GPU required
