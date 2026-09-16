# Design: queue-busy-chat-backends

## Context

`routes.begin_inference` already implements a wait loop over `BackendAvailability.begin_request()`; the bound is `ADMISSION_WAIT_SECONDS`, read from the environment and defaulting to 0, so today it is a reject-only gate. Rejection is 503 `BACKEND_BUSY`, which LiteLLM cannot tell apart from `BACKEND_UNAVAILABLE`. Router settings: `allowed_fails: 1`, `cooldown_time: 90`, `num_retries: 1`, `timeout: 180`. An untracked `tests/test_chat_admission.py` already asserts the wait behaviour, so the intent exists; this change makes it the default and completes the signalling.

## Goals / Non-Goals

**Goals:** no error for overlap that resolves within a generation; busy never poisons routing; timeouts consistent end to end; clients capped at the proxy.
**Non-Goals:** global queue, priorities, extra slots.

## Decisions

1. **Wait bound = one generation.** Default `ADMISSION_WAIT_SECONDS=60` for chat (512 max_tokens at ~30 tok/s plus prompt processing ≈ 30-45 s). Set in `x-gpu-env-common` so every chat replica inherits it; canaries keep their own value.
2. **Busy → 429 + Retry-After, not 503.** LiteLLM's router treats 429 as rate-limit: it tries another deployment and, when none is free, surfaces the 429 rather than cooling the deployment (verify against the pinned LiteLLM version in a router unit test; if the version cools on 429, set `disable_cooldowns` for busy via `cooldown_time` on the 429 path or a custom `allowed_fails_policy`). `Retry-After` = min(remaining generation estimate, 30).
3. **Cooldown tuning in `litellm/config.base.yaml`**: `allowed_fails: 3`, `cooldown_time: 20`, `num_retries: 2`, per-chat-model `timeout: 240` (60 wait + 180 generation ceiling). The wrapper's downstream httpx timeout stays ≥ 180.
4. **Per-key caps via LiteLLM key metadata** (`max_parallel_requests`), documented in the key-generation command in CLAUDE.md. Rediska key: 2.
5. **Metrics**: `inference_admission_total{status=admitted|queued|rejected}` and `inference_admission_wait_seconds` histogram; alert on rejected rate.

## Risks / Trade-offs

- [Queued requests hold an HTTP connection on the 2-core host] → bound is 60 s and per-key caps limit depth; uvicorn handles idle awaits cheaply.
- [LiteLLM version semantics for 429 differ] → covered by a router-level test using the pinned image before rollout.
- [Latency instead of fast failure surprises interactive clients] → documented in the contract; `Retry-After` lets them show progress.

## Migration Plan

Roll the wrapper env change with a rolling `gpu-server-1..6` restart (health-gated); restart LiteLLM for router settings; rotate key caps without downtime. Rollback: `ADMISSION_WAIT_SECONDS=0` and previous router block.

## Open Questions

- Exact `Retry-After` estimator (fixed 15 s vs remaining-generation estimate from slot state).
