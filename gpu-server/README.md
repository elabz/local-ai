# HeartCode GPU Server

GPU inference server using llama.cpp, optimized for Pascal GPUs (P106-100, P104-100).

## Quick Start

### 1. Download a Model

```bash
./scripts/download_model.sh stheno Q4_K_M
```

Available models:
- `stheno` - Stheno L3.1 8B (recommended for roleplay)
- `lumimaid` - Lumimaid 8B (creative writing)

Quantizations:
- `Q4_K_M` - 4-bit, ~5GB, fits 6GB VRAM (P106-100)
- `Q5_K_M` - 5-bit, ~6GB, needs 8GB VRAM (P104-100)

### 2. Start the Server

```bash
# Single GPU
docker-compose up gpu-server-1

# Multiple GPUs with load balancer
docker-compose up -d
```

### 3. Test the Server

```bash
./scripts/health_check.sh http://localhost:8080
```

## API Endpoints

### OpenAI-Compatible

```bash
# Chat completion
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'

# Text completion
curl http://localhost:8080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Once upon a time",
    "max_tokens": 100
  }'
```

### Streaming

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "max_tokens": 100,
    "stream": true
  }'
```

### Health & Metrics

```bash
# Health check
curl http://localhost:8080/health

# Prometheus metrics
curl http://localhost:9091/metrics
```

## GPU Memory Requirements

| Quantization | Model Size | Min VRAM | Recommended GPU |
|-------------|-----------|----------|-----------------|
| Q4_K_M | 4.9 GB | 6 GB | P106-100 |
| Q5_K_M | 5.7 GB | 7 GB | P104-100 |
| Q6_K | 6.6 GB | 8 GB | P104-100 |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LiteLLM Proxy                        │
│                  (Load Balancer)                        │
│                   Port 4000                             │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│   GPU Server 1  │     │   GPU Server 2  │
│   (P106-100)    │     │   (P104-100)    │
│   Port 8080     │     │   Port 8081     │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  llama.cpp      │     │  llama.cpp      │
│  server         │     │  server         │
│  Port 8081      │     │  Port 8081      │
└─────────────────┘     └─────────────────┘
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| MODEL_PATH | /models/model.gguf | Path to GGUF model |
| N_GPU_LAYERS | 33 | Layers to offload to GPU |
| N_CTX | 4096 | Context size |
| N_BATCH | 512 | Batch size |
| N_THREADS | 4 | CPU threads |
| PORT | 8080 | API port |
| METRICS_PORT | 9091 | Prometheus metrics port |

## Benchmarking

```bash
python scripts/benchmark.py \
  --url http://localhost:8080 \
  --requests 20 \
  --concurrency 4 \
  --max-tokens 100
```

## Monitoring

Access Prometheus at http://localhost:9090

Key metrics:
- `inference_requests_total` - Request count by status
- `inference_duration_seconds` - Latency histogram
- `gpu_memory_used_bytes` - VRAM usage
- `gpu_temperature_celsius` - GPU temperature
- `active_requests` - Current in-flight requests
