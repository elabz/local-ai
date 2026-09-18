## Why

Only the Python wrappers (chat, vision-embed, DINOv2) exported metrics. llama.cpp's own series (tokens processed, KV-cache use, slot and queue state, `llamacpp:*`) came from no server at all, and the two text-embed `llama-server` processes had no metrics endpoint. Prometheus also scraped two containers that no longer exist (`pea-image-2`, `pea-embed-vision-3`), so it had 2 of 18 targets permanently down. The owner asked (2026-09-18) that every llama-server, chat or embedding, provide metrics.

## What Changes

- Every `llama-server` runs with `--metrics`: the chat wrapper always passes it (`server.py`), and the text-embed anchor, `qwen3-canary`, and the canary and nothink compose files include it.
- The chat wrapper relays llama-server's metrics read-only at `/llama/metrics` (llama-server stays on loopback, so nothing bypasses admission). Text-embed servers are scraped directly at `:8090/metrics`.
- Prometheus: a `llama-server` job covers all 8 servers; a `dino-embed` job is added (never scraped before); targets for removed containers are dropped.

## Capabilities

### New Capabilities
- `inference-metrics`: every inference server on PEA exposes Prometheus metrics, llama-server processes expose llama.cpp's own series, and Prometheus scrapes exactly the containers that exist.

### Modified Capabilities

## Impact

`gpu-server/server.py`, `routes.py`, `llama_client.py`, `docker-compose*.yml`, `configs/prometheus.yml`, tests. Rollout: embed servers recreated, chat workers restarted one at a time (2026-09-18, 18:36Z onward). No API change for clients.
