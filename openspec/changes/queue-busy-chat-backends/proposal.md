# Proposal: queue-busy-chat-backends

## Why

A busy chat backend is currently indistinguishable from a dead one. The wrapper's admission control (`ADMISSION_WAIT_SECONDS`, default 0) rejects any request that finds the single slot occupied with an immediate 503; LiteLLM (`allowed_fails: 1`, `cooldown_time: 90`) then removes that deployment for 90 s, so one overlapping request converts a busy replica into a 429 storm for every client. With few replicas per model group this turns ordinary concurrency into an outage, as the 2026-08-27 → 09-16 NSFW incident showed. llama-server itself would have queued the request.

## What Changes

- **Queue instead of reject**: chat backends wait a bounded time for a slot (`ADMISSION_WAIT_SECONDS` > 0 by default, sized to one generation) before returning a busy response.
- **Busy is not failure**: a request that exceeds the admission wait returns 429 with `Retry-After`, and LiteLLM treats that as a routing hint, not a deployment failure. 503 is reserved for a backend that is actually unavailable (GPU gone, child dead, downstream timeout). Cooldown thresholds are raised so a single transient busy/503 does not remove a deployment.
- **Timeouts made consistent**: LiteLLM per-model timeout ≥ admission wait + worst-case generation; wrapper downstream timeout ≥ generation.
- **Per-key concurrency**: every LiteLLM key gets `max_parallel_requests` no greater than the slot count of the model groups it may call; batch consumers (Rediska) get 1-2.
- **Client contract**: a short documented rule set for proxy consumers — bounded concurrency, honour `Retry-After`, jittered exponential backoff, never fan out beyond the group's slot count.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `gpu-inference-availability`: busy backends queue within a bound and signal "busy" distinctly from "unavailable"; proxy cooldown applies only to unavailable deployments; consumer keys are concurrency-capped.

## Impact

- `gpu-server/routes.py` (admission wait default, busy response code/headers), `gpu-server/availability.py`, `gpu-server/config.py`, compose `x-gpu-env-common`; `litellm/config.base.yaml` router settings (`allowed_fails`, `cooldown_time`, `timeout`); LiteLLM key metadata; `docs/` client contract; Prometheus metrics for queued/rejected admissions.
- Behaviour change for consumers: a busy backend now adds latency (up to the wait bound) instead of failing fast.

## Non-goals

- No cross-replica global queue or priority scheduling (see `scale-chat-concurrency`).
- No change to slot count per GPU.
- No change for embedding, STT, TTS or image routes beyond documenting that the contract applies to them.
