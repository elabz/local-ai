# Tasks — serve-public-inference-api

Driven by HeartCode `harden-public-inference-api` (tasks 1.3, 1.5, 1.6).

## 1. Sampler passthrough (Pea wrapper)
- [x] 1.1 Measure what reaches llama.cpp via `/slots`, direct and through LiteLLM — 2026-10-10: temperature/top_p/top_k/min_p/max_tokens/repeat_penalty arrive; stop, seed, presence/frequency/repetition_penalty dropped by the wrapper's request model
- [x] 1.2 Accept and forward the missing fields on both chat paths; tests in `test_sampling_passthrough.py`
- [x] 1.3 Roll the chat slots on Pea and re-run the `/slots` and stop-string checks through LiteLLM — 2026-10-10: no rebuild needed (routes.py/llama_client.py are bind-mounted). `git pull --ff-only` to fa82aae, then `docker restart` of pea-gpu-1,2,3,4,6 one at a time, each ready in 50–64 s. Through the live proxy: repetition_penalty 1.13 → slot repeat_penalty 1.13, presence 0.41, frequency 0.29, seed 4242; `stop: ["7"]` stops at "6," streaming and not. Pea's root disk was at 100% (0 bytes for boss, inside the 5% reserve): owner approved deleting eight model files no process maps (Lumimaid non-imat duplicate and the Gemma/Qwen canaries, ~45 GB) → 79%

## 2. Public guard (LiteLLM on elm)
- [x] 2.1 Measure team-level `max_parallel_requests` on 1.81.9 — not enforced (3 concurrent admitted at a cap of 1); probe team and key deleted
- [x] 2.2 `public_api_guard.py`: marker, size limits, sampler clamps, per-group admission with release on success/failure/stream end and stale expiry; `test_public_api_guard.py`
- [x] 2.3 Register in `config.base.yaml`, render `config.yaml`, mount and `PUBLIC_API_*` env in compose
- [x] 2.4 Verify against the pinned image with a local proxy + Postgres: clamps reach the slot, 413/400 bodies, 429 + `Retry-After: 5` during a stream (alias too), slot freed after stream end and after client disconnect, first-party key untouched
- [x] 2.5 Deploy on elm and repeat 2.4's checks against the live proxy with a HeartCode-minted key — 2026-10-10: `up -d litellm` (not `restart`: the compose spec gained a mount and env), all 12 model groups intact. With a key minted by HeartCode's dev backend: max_tokens 5000/temperature 6/top_k 999 reached the NSFW slot as 1024/2.0/200; 101 messages → 413; a second public SFW request during a public stream → 429 `retry-after: 5` while first-party SFW and public NSFW were admitted; slot freed at stream end. Key revoked through HeartCode, then 401
