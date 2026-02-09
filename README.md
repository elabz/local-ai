# Local AI

Shared GPU inference infrastructure for local network projects. Provides OpenAI-compatible API endpoints for chat completion, embeddings, and image generation.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  ASH Server (192.168.0.145) - gpu-server/                    │
│                                                              │
│  GPU 1-4: llama.cpp SFW chat    (ports 8080-8083)           │
│  GPU 5-8: llama.cpp NSFW chat   (ports 8084-8087)           │
│  GPU 1-8: llama.cpp embeddings  (ports 8090-8097)           │
│  8x NVIDIA P106-100 (6GB VRAM each), 32GB RAM               │
└───────────────────────┬──────────────────────────────────────┘
                        │ LAN
┌───────────────────────▼──────────────────────────────────────┐
│  Prod Server (192.168.0.152) - litellm/ + monitoring/        │
│                                                              │
│  LiteLLM Proxy      (port 4000)  ──→ ASH:8080-8097          │
│  PostgreSQL          (port 5432)  (API key storage)          │
│  Langfuse            (port 3002)  (LLM observability)        │
│  Prometheus/Grafana  (ports 9090/3001)                       │
└───────────────────────┬──────────────────────────────────────┘
                        │ LAN
│  Clients: Any project on the network                         │
│  → http://192.168.0.152:4000/v1/chat/completions             │
│  → http://192.168.0.152:4000/v1/embeddings                   │

┌──────────────────────────────────────────────────────────────┐
│  Image Server (192.168.0.143) - gpu-image-server/            │
│  LocalAI + Stable Diffusion (2x RTX 3070, port 5100)        │
└──────────────────────────────────────────────────────────────┘
```

## Components

| Directory | Description | Deployed On |
|-----------|-------------|-------------|
| `gpu-server/` | llama.cpp inference servers (8x GPU) | ASH (192.168.0.145) |
| `litellm/` | LiteLLM proxy + PostgreSQL for API keys | Prod (192.168.0.152) |
| `gpu-image-server/` | Stable Diffusion image generation | Image (192.168.0.143) |
| `monitoring/` | Prometheus + Grafana dashboards | Prod (192.168.0.152) |
| `langfuse/` | LLM observability and tracing | Prod (192.168.0.152) |
| `load-tests/` | k6 stress tests and analysis tools | Dev machine |

## Quick Start

### 1. GPU Servers (ASH)

```bash
cd gpu-server
cp .env.example .env    # Configure model paths
docker compose up -d    # Start 8 chat + 8 embedding servers
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
  -d '{"models": ["local-ai-chat-sfw", "local-ai-chat-nsfw", "local-ai-embed"],
       "key_alias": "my-project"}'
```

### 4. Use the API

```bash
# Chat completion
curl http://192.168.0.152:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "local-ai-chat-sfw",
       "messages": [{"role": "user", "content": "Hello!"}],
       "max_tokens": 256}'

# Embeddings
curl http://192.168.0.152:4000/v1/embeddings \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "local-ai-embed",
       "input": "Text to embed"}'
```

## Models

| Model Name | GPUs | Hardware | Description |
|-----------|------|----------|-------------|
| `local-ai-chat-sfw` | 1-4 | P106-100 | Stheno-L3.1-8B (SFW chat) |
| `local-ai-chat-nsfw` | 5-8 | P106-100 | Lumimaid-v0.2-8B (NSFW chat) |
| `local-ai-chat` | 1-4 | P106-100 | Alias for local-ai-chat-sfw |
| `local-ai-embed` | 1-8 | P106-100 | nomic-embed-text-v1.5 |

## API Key Management

LiteLLM uses PostgreSQL-backed virtual keys. Manage via the master key:

```bash
# Create key with model restrictions and rate limits
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models": ["local-ai-chat-sfw", "local-ai-embed"],
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

## Monitoring

```bash
# Start monitoring stack
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
