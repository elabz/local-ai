## 1. Backend wrapper

- [x] 1.1 Default `ADMISSION_WAIT_SECONDS` to 60 for chat replicas in `x-gpu-env-common`; keep `config.py` override
- [x] 1.2 Change bound-exceeded response to 429 with `Retry-After` and `BACKEND_BUSY`; keep 503 for `GPU_UNAVAILABLE`/`BACKEND_UNAVAILABLE`
- [x] 1.3 Add admission metrics (`admitted|queued|rejected`, wait histogram); commit and extend `tests/test_chat_admission.py`

## 2. Proxy

- [x] 2.1 Router settings in `litellm/config.base.yaml`: `allowed_fails: 3`, `cooldown_time: 20`, `num_retries: 2`, chat `timeout: 240`; re-render `litellm/config.yaml`
- [x] 2.2 Router test against the pinned LiteLLM image proving a 429 from a deployment does not cool it and is retried elsewhere
- [x] 2.3 Set `max_parallel_requests` on every issued key (Rediska = 2); document the cap in the key-generation procedure

## 3. Contract and observability

- [x] 3.1 Write `docs/proxy-client-contract.md` (bounded concurrency, `Retry-After`, jittered backoff, no fan-out beyond slot count) and link from CLAUDE.md
- [x] 3.2 Prometheus alert on admission `rejected` rate and on LiteLLM cooldown events
- [x] 3.3 Rolling deploy of chat replicas and LiteLLM; verify with a 7-way concurrent burst against `heartcode-chat-nsfw` that produces zero 503s and zero cooldowns

## Deploy record (2026-09-16)

- Keys capped on Prod via `litellm/scripts/cap-key-concurrency.py --apply`: heartcode-backend 8, manuals-pilot 3, vox-speech 4. No Rediska key exists yet; issue it with `max_parallel_requests: 2`.
- LiteLLM recreated on Prod with the rendered config and pinned digest (litellm 1.81.9); `heartcode-chat-nsfw` 3/3 healthy.
- Rolling recreate of `gpu-server-1..6` on PEA, each health-gated (40-55s to healthy); every replica reports `ADMISSION_WAIT_SECONDS=60`.
- 7-way concurrent burst at `heartcode-chat-nsfw` through the proxy: 7/7 HTTP 200, zero 503, zero `litellm_deployment_cooled_down_total` increments. Replica counters afterwards: admitted 6, queued 1, rejected 0 (the queue was exercised).
- `pea-prometheus` had been exited for three weeks; started it. 33 rules loaded incl. the five new ones; `litellm-proxy` target up and `inference_admission_total` scraped.
