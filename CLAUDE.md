# CLAUDE.md

## Project Overview

Local AI is a shared GPU inference infrastructure for local network projects. It provides OpenAI-compatible API endpoints via LiteLLM proxy, backed by llama.cpp GPU servers and LocalAI for image generation.

## Repository Structure

```
local-ai/
├── gpu-server/           # llama.cpp + LocalAI inference servers (PEA)
│   ├── docker-compose.yml  # 6 chat + 2 text + 2 vision + 2 DINOv2-visual embed + 2 image + monitoring
│   ├── server.py           # FastAPI wrapper with metrics
│   ├── llama_client.py     # Async client proxying to llama.cpp native API
│   ├── routes.py           # OpenAI-compatible API routes
│   ├── config.py           # Pydantic settings from env vars
│   ├── metrics.py          # Prometheus metrics collection
│   ├── Dockerfile          # CUDA build for Pascal GPUs (no AVX)
│   ├── vision-embed/       # PyTorch + transformers nomic-embed-vision-v1.5 + text-v1.5 (deployed)
│   ├── dino-embed/         # PyTorch + transformers DINOv2 ViT-L/14, image-only visual similarity (deployed)
│   ├── multimodal-embed/   # SHELVED — colpali-engine BiQwen2.5 (nomic-embed-multimodal-3b)
│   ├── configs/            # prometheus.yml, alert_rules.yml, alertmanager.yml, entrypoint-wrapper.sh
│   ├── scripts/            # setup-pea.sh, download-models.sh, watchdog, diagnostics
│   └── models/             # heartcode-image.yaml (GGUF files excluded via .gitignore)
├── litellm/              # LiteLLM proxy + PostgreSQL API key management
│   ├── docker-compose.yml  # LiteLLM + PostgreSQL
│   ├── config.yaml         # Production config (model routing, rate limits)
│   └── config-local.yaml   # Local dev config
├── monitoring/           # NOT DEPLOYED — reference Grafana dashboards only (live monitoring is in gpu-server/)
│   └── grafana/
├── langfuse/             # LLM observability
│   └── docker-compose.yml
├── load-tests/           # k6 stress tests
│   ├── stress-all-gpus.js
│   └── monitor.sh
└── docs/                 # Documentation
    ├── pea-server-setup.md   # Comprehensive setup guide
    ├── proxy-client-contract.md  # Rules for proxy consumers: concurrency caps, 429/503, backoff
    └── load-test-findings.md # Capacity analysis
```

## Deployment Topology

- **PEA (192.168.70.144)**: All GPU servers — 3 SFW + 3 NSFW chat (GPU 4-6), each co-located with one embed server (vision on 1-2, DINOv2-visual on 3+6, text on 4-5) + image on 8, speech on 7 — `gpu-server/docker-compose.yml`. GPU 5 corrupts generation above ~7.6 GiB per process: only the fleet 8B config belongs there.
- **Prod (192.168.70.152)**: LiteLLM proxy + monitoring — `litellm/docker-compose.yml`

## Common Commands

### GPU Server (on PEA - 192.168.70.144)
```bash
cd gpu-server
docker compose up -d                    # Start all GPU servers
docker compose ps                       # Check health (every service Up/healthy)
docker compose logs -f pea-gpu-1        # View specific GPU logs
docker compose restart gpu-server-1     # Restart one server
docker build -t local-ai-llama:latest . # Rebuild llama.cpp image
./scripts/setup-pea.sh                  # Full deployment from scratch
./scripts/download-models.sh            # Download all GGUF models
```

### LiteLLM Proxy (on Prod - 192.168.70.152)
```bash
cd litellm
docker compose up -d                    # Start LiteLLM + PostgreSQL
docker compose logs -f litellm          # View proxy logs
docker compose restart litellm          # Restart after config changes

# API Key Management — every key MUST carry max_parallel_requests no greater
# than the total slot count of the model groups it may call (chat groups have
# 3 slots each; Rediska is capped at 4, its agreed worker count). Send the consumer
# docs/proxy-client-contract.md with the key.
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models":["heartcode-chat-sfw","heartcode-chat-nsfw","heartcode-embed","heartcode-image"],"key_alias":"test","max_parallel_requests":6}'
python3 scripts/cap-key-concurrency.py --apply   # audit/apply caps on all issued keys
```

### Load Testing
```bash
cd load-tests
k6 run -e API_KEY=$KEY stress-all-gpus.js
./monitor.sh                            # Real-time monitoring
```

## CI/CD

Two workflows under `.github/workflows/`:

- **`gpu-build.yml` (CI)** — runs on every push/PR on GitHub-hosted runners (no secrets, no LAN). Jobs: `compose-validate` (`docker compose config` for every stack), `litellm-validate` (`litellm/validate_config.py`), `model-manifest-validate` (`render-config.py --check`), `python-lint` (ruff + `py_compile`), and a **build-only**, path-filtered `gpu-build` (llama.cpp image, no push). GitHub-hosted runners **cannot reach the 192.168.70.x LAN**, so CI never deploys.
- **`deploy.yml` (CD)** — manual `workflow_dispatch` (`target`: `litellm`/`gpu-server`/`both`) on a **self-hosted runner labeled `homelab`** (registered on Prod; can SSH to PEA over the LAN). Gated by the `production` Environment. LiteLLM = `git checkout <sha>` + `docker compose up -d litellm` + health check on Prod; GPU server = SSH to PEA, regenerate env, native `docker build`, rolling `gpu-server-1..6` restart with `/health` gating.

### Changing a model or its tenancy (single source of truth)

Edit **`gpu-server/models.yaml`** only, then regenerate:
```bash
cd gpu-server && python3 scripts/render-config.py     # writes the generated files
python3 scripts/render-config.py --check              # what CI runs (fails on drift)
```
This renders (all **generated — do not hand-edit**): `gpu-server/models.generated.env` (chat `GPU_N_MODEL_*`), `litellm/config.yaml` (merged from `litellm/config.base.yaml` + the manifest), `gpu-server/models.download.tsv` (consumed by `scripts/download-models.sh`), and the Models and Port Layout tables in this file (between the `BEGIN/END GENERATED` markers; the prose around them is hand-written). Secrets stay in the gitignored `gpu-server/.env`. Edit routing/retry/auth knobs in `litellm/config.base.yaml`. Structural changes (a GPU's *service kind*, e.g. chat→embed) are still manual `docker-compose.yml` edits.

**Capacity floor (`min_replicas`)**: every model group declares `min_replicas`, and `render-config.py` (and so CI) fails when fewer deployments are listed. Removing a replica for a canary, maintenance or a dead card is only allowed in an edit that **also lowers `min_replicas` with a comment giving the date and reason**, e.g. `min_replicas: 2  # lowered 2026-09-16 from 3: GPU 6 hosts the SFW canary`. Never lower it without that comment, and raise it back in the edit that restores the replica.

Then deploy via `deploy.yml`, or **manually** (fallback if the runner is down):
```bash
# Prod (LiteLLM):  git pull && docker compose -f litellm/docker-compose.yml up -d litellm
# PEA (GPU):       git pull && cd gpu-server && python3 scripts/render-config.py \
#                  && docker build -t local-ai-llama:latest . \
#                  && docker compose --env-file .env --env-file models.generated.env up -d
```

## Models

<!-- BEGIN GENERATED: models -->
<!-- Generated by gpu-server/scripts/render-config.py from gpu-server/models.yaml. Do not edit by hand; `render-config.py --check` fails on drift. -->

| API Name | Type | GPUs | Replicas (min) | Model | Quant | Chat Template |
|----------|------|------|----------------|-------|-------|---------------|
| `heartcode-chat-sfw` | Chat (SFW) | 1-3 | 3 (3) | Llama-3.1-8B-Stheno-v3.4 | Q5_K_M | GGUF-embedded (`--jinja`) |
| `heartcode-chat-nsfw` | Chat (NSFW) | 4-6 | 3 (3) | Lumimaid-v0.2-8B (NeverSleep) | Q5_K_M | GGUF-embedded (`--jinja`) |
| `heartcode-embed` | Embedding (text) | 4-5 | 2 (2) | nomic-embed-text-v1.5 | Q8_0 | — |
| `heartcode-embed-vision` | Embedding (text + image) | 1-2 | 2 (2) | nomic-embed-vision-v1.5 + nomic-embed-text-v1.5 | fp32¹ | — |
| `heartcode-embed-visual` | Embedding (image-only) | 3, 6 | 2 (2) | DINOv2 ViT-L/14 (with registers) | fp32² | — |
| `heartcode-image` | Image | 8 | 1 (1) | Segmind SSD-1B (SDXL distilled) | FP16 | — |
| `heartcode-stt` | Speech-to-text | 7 | 1 (1) | faster-whisper small.en (speaches) | int8 | — |
| `heartcode-tts` | Text-to-speech | 7 | 1 (1) | Kokoro-82M (kokoro-fastapi) | — | — |

**Aliases**: `heartcode-default`, `heartcode-sfw`, `heartcode-chat` → `heartcode-chat-sfw` | `heartcode-nsfw` → `heartcode-chat-nsfw`

<!-- END GENERATED: models -->

Embed tier is **2 of each type**, co-located one-per-chat-GPU (`rebalance-embed-image-gpus` → `serve-dinov2-visual-embed`).

¹ Vision embeddings are **768-d** in a shared text+image space (nomic-embed-vision-v1.5 ↔ nomic-embed-text-v1.5). fp32, ~1.1GB VRAM each, co-located on SFW chat GPU 1-2; text query gets the `search_query:` prefix. **Apache-2.0.** `heartcode-embed` (text-only) is the legacy `nomic-embed-text-v1.5` GGUF co-located on NSFW chat GPU 4-5.

² **`heartcode-embed-visual`** = **DINOv2 ViT-L/14 +registers, 1024-d, image-only** — fine-grained visual / same-object similarity (image→image). **Separate vector space** from the CLIP `heartcode-embed-vision` (downstream keeps its own index); text input → 400. ~1.3GB VRAM, co-located on chat GPU 3 + 6 (~7.5GB/8GB — ViT-B fallback if OOM). **Apache-2.0.** See `gpu-server/dino-embed/`, change `serve-dinov2-visual-embed`, and `docs/embedding-model-eval.md`. All embeddings are **serving-only** (storage/search downstream). The BiQwen2.5 multimodal model is **shelved** (`gpu-server/multimodal-embed/`, change `switch-to-nomic-multimodal-embed`).

## Port Layout (PEA)

<!-- BEGIN GENERATED: ports -->
<!-- Generated by gpu-server/scripts/render-config.py from gpu-server/models.yaml. Do not edit by hand; `render-config.py --check` fails on drift. -->

| Ports | Model group | Model | GPU | Shares GPU with |
|-------|-------------|-------|-----|-----------------|
| 5100 | `heartcode-image` | Segmind SSD-1B (SDXL distilled) | GPU 8 | — |
| 8080-8082 | `heartcode-chat-sfw` | Llama-3.1-8B-Stheno-v3.4 | GPU 1-3 | `heartcode-embed-vision` (GPU 1-2), `heartcode-embed-visual` (GPU 3) |
| 8083-8085 | `heartcode-chat-nsfw` | Lumimaid-v0.2-8B (NeverSleep) | GPU 4-6 | `heartcode-embed` (GPU 4-5), `heartcode-embed-visual` (GPU 6) |
| 8093-8094 | `heartcode-embed` | nomic-embed-text-v1.5 | GPU 4-5 | `heartcode-chat-nsfw` (GPU 4-5) |
| 8101-8102 | `heartcode-embed-vision` | nomic-embed-vision-v1.5 + nomic-embed-text-v1.5 | GPU 1-2 | `heartcode-chat-sfw` (GPU 1-2) |
| 8104-8105 | `heartcode-embed-visual` | DINOv2 ViT-L/14 (with registers) | GPU 3, 6 | `heartcode-chat-sfw` (GPU 3), `heartcode-chat-nsfw` (GPU 6) |
| 8200 | `heartcode-stt` | faster-whisper small.en (speaches) | GPU 7 | `heartcode-tts` (GPU 7) |
| 8201 | `heartcode-tts` | Kokoro-82M (kokoro-fastapi) | GPU 7 | `heartcode-stt` (GPU 7) |

<!-- END GENERATED: ports -->

Monitoring (hand-maintained; not in `models.yaml`):

| Port | Service |
|------|---------|
| 9099 | Prometheus |
| 9093 | Alertmanager → Slack `#hardware-alerts` |
| 3001 | Grafana |
| 9100 | Node Exporter |

## Key Configuration

### GPU Server (`gpu-server/docker-compose.yml`)
- Memory limits (host budget, enforced in CI by `scripts/check-memory-budget.py`): every default-started service has `mem_limit`, with `memswap_limit` = limit + 512m, and the limits sum to ≤ host RAM − 2 GiB (29,975 MiB; currently 29,376). Chat 1792m each, text-embed 512m, vision-embed 2048m, DINOv2 1536m, image 4096m, STT 1792m, TTS 2816m, Alertmanager 64m. Adding a service means shrinking another (change `bound-llama-host-prompt-cache`)
- `N_GPU_LAYERS=33`, `N_CTX=16384`, `N_BATCH=128`, `N_UBATCH=64`, `N_THREADS=2`
- KV cache: `q8_0` quantization for both keys and values
- `EXTRA_ARGS: "--jinja"` — enables Jinja chat templates for Llama 3.1 models
- `CACHE_REUSE=256` — prompt caching for faster TTFT
- `--metrics` on every llama-server: chat workers relay llama.cpp's `llamacpp:*` series at `:8080/llama/metrics` (llama-server stays on loopback), text-embed at `:8090/metrics`; Prometheus job `llama-server` (spec `inference-metrics`)
- `CACHE_RAM=1024` — llama-server `--cache-ram`: bounds the host-RAM prompt cache per worker (~4 HeartCode 4k-token sessions). Never unset: llama.cpp's implicit 8192 MiB let six workers OOM the host on 2026-09-18. Never `0`: it may disable `--cache-reuse`
- Power limit: 120W per GPU (`nvidia-power-limit.service`)

### Vision Embedding Server (`gpu-server/vision-embed/`)
- PyTorch + `transformers` (`trust_remote_code`) FastAPI service loading the nomic v1.5 pair — NOT llama.cpp
- **2 instances co-located on SFW chat GPUs 1-2** (`vision-embed-1/2`, ports 8101-8102); **fp32**, ~1.1GB VRAM each, `MAX_BATCH_SIZE=4` to bound activation memory on the shared 8GB cards
- OpenAI `/v1/embeddings` accepts text strings, `data:` image URIs, and `{"image": ...}` objects → **768-d** shared-space vectors (text query gets the `search_query:` prefix; see `vision-embed/README.md`)
- `nomic-embed-vision-v1.5` + `nomic-embed-text-v1.5` snapshotted into `/models` HF cache by `download-models.sh`
- **Serving only** — no vector storage/search in this repo (downstream app owns that)
- ⚠️ GPU 1-2 run ~7.4GB/8GB (chat + vision) — watch for OOM under peak chat-context + image load
- Model choice is provisional pending the on-corpus eval — see `docs/embedding-model-eval.md`
- Shelved alternative: `gpu-server/multimodal-embed/` (BiQwen2.5, document retrieval) — see change `switch-to-nomic-multimodal-embed`

### LiteLLM Config (`litellm/config.yaml`)
- All endpoints point to PEA (192.168.70.144)
- Routing: `least-busy` strategy with 2 retries
- Rate limits: per-group `rate_limit` in `gpu-server/models.yaml`, rendered into `router_settings.model_rate_limits`
- Deployments per group, their ports and GPUs: the generated [Models](#models) and [Port Layout](#port-layout-pea) tables. BiQwen2.5 (`:8100`) shelved
- Busy is not failure: chat wrappers queue up to `ADMISSION_WAIT_SECONDS=60` then answer `429 BACKEND_BUSY` + `Retry-After`; the router retries a sibling (`num_retries: 2`) and never cools a replica for 429 (`allowed_fails_policy`). Cooldown needs 3 real failures (503/connection) and lasts 20s. Chat deployment `timeout: 240`.
- Health checks every 15s; per-key `max_parallel_requests` mandatory — see `docs/proxy-client-contract.md`

### Image Server (`gpu-server/models/heartcode-image.yaml`)
- **1 instance** (`image-server` → `pea-image-1`, GPU 8, `:5100`) behind `heartcode-image`. The second replica (`image-server-2`, GPU 7, `:5101`) is retired; GPU 7 serves speech
- Backend: `diffusers` (auto-installed from LocalAI gallery on first start)
- Pipeline: `StableDiffusionXLPipeline` with `k_dpmpp_2m` scheduler
- Persistent backend volume: `image_backends` mounted at `/backends` (survives restarts; a future second replica can reuse it with no re-download)
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

### PEA (192.168.70.144)
- **CPU**: Intel Celeron 3865U (2-core, 1.8GHz, no AVX/AVX2/BMI2)
- **RAM**: 32GB DDR4
- **GPUs**: 8x P104-100 (8GB VRAM, Pascal, compute 6.1)
- **GPU numbering**: 1-indexed in configs (GPU 1-8), 0-indexed physical (`NVIDIA_VISIBLE_DEVICES=0-7`)
- **Safe limits**: 35 RPM SFW, 34 RPM NSFW, 40 RPM vision embed (2), 28 RPM text embed (2), 40 RPM visual/DINOv2 (2)
- **GPU allocation**: 1 embed server co-located per chat GPU — GPU 1-2 SFW chat + **vision-embed**, GPU 3 SFW chat + **DINOv2-visual**, GPU 4-5 NSFW chat + **text-embed**, GPU 6 NSFW chat + **DINOv2-visual**, GPU 7 **speech** (STT + TTS), GPU 8 **image**. GPU 1-2 ~7.4GB, GPU 3/6 ~7.5GB (chat+DINOv2) — monitor under peak load.

### Prod (192.168.70.152)
- Runs LiteLLM proxy and PostgreSQL (monitoring and alerting run on PEA)
- No GPU required
