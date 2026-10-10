# Tasks — serve-public-inference-api

Driven by HeartCode `harden-public-inference-api` (tasks 1.3, 1.5, 1.6).

## 1. Sampler passthrough (Pea wrapper)
- [x] 1.1 Measure what reaches llama.cpp via `/slots`, direct and through LiteLLM — 2026-10-10: temperature/top_p/top_k/min_p/max_tokens/repeat_penalty arrive; stop, seed, presence/frequency/repetition_penalty dropped by the wrapper's request model
- [x] 1.2 Accept and forward the missing fields on both chat paths; tests in `test_sampling_passthrough.py`
- [ ] 1.3 Rebuild `local-ai-llama` on Pea and roll the chat slots one at a time; re-run the `/slots` and stop-string checks through LiteLLM

## 2. Public guard (LiteLLM on elm)
- [x] 2.1 Measure team-level `max_parallel_requests` on 1.81.9 — not enforced (3 concurrent admitted at a cap of 1); probe team and key deleted
- [x] 2.2 `public_api_guard.py`: marker, size limits, sampler clamps, per-group admission with release on success/failure/stream end and stale expiry; `test_public_api_guard.py`
- [x] 2.3 Register in `config.base.yaml`, render `config.yaml`, mount and `PUBLIC_API_*` env in compose
- [x] 2.4 Verify against the pinned image with a local proxy + Postgres: clamps reach the slot, 413/400 bodies, 429 + `Retry-After: 5` during a stream (alias too), slot freed after stream end and after client disconnect, first-party key untouched
- [ ] 2.5 Deploy on elm (`git pull --ff-only`, `docker compose -f litellm/docker-compose.yml restart litellm`) and repeat 2.4's checks against the live proxy with a HeartCode-minted key
