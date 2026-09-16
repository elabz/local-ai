## 1. Backend wrapper

- [x] 1.1 Default `ADMISSION_WAIT_SECONDS` to 60 for chat replicas in `x-gpu-env-common`; keep `config.py` override
- [x] 1.2 Change bound-exceeded response to 429 with `Retry-After` and `BACKEND_BUSY`; keep 503 for `GPU_UNAVAILABLE`/`BACKEND_UNAVAILABLE`
- [x] 1.3 Add admission metrics (`admitted|queued|rejected`, wait histogram); commit and extend `tests/test_chat_admission.py`

## 2. Proxy

- [x] 2.1 Router settings in `litellm/config.base.yaml`: `allowed_fails: 3`, `cooldown_time: 20`, `num_retries: 2`, chat `timeout: 240`; re-render `litellm/config.yaml`
- [x] 2.2 Router test against the pinned LiteLLM image proving a 429 from a deployment does not cool it and is retried elsewhere
- [ ] 2.3 Set `max_parallel_requests` on every issued key (Rediska = 2); document the cap in the key-generation procedure

## 3. Contract and observability

- [ ] 3.1 Write `docs/proxy-client-contract.md` (bounded concurrency, `Retry-After`, jittered backoff, no fan-out beyond slot count) and link from CLAUDE.md
- [ ] 3.2 Prometheus alert on admission `rejected` rate and on LiteLLM cooldown events
- [ ] 3.3 Rolling deploy of chat replicas and LiteLLM; verify with a 7-way concurrent burst against `heartcode-chat-nsfw` that produces zero 503s and zero cooldowns
