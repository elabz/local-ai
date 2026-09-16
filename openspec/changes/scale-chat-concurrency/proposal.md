# Proposal: scale-chat-concurrency

## Why

With one slot per GPU, six chat cards deliver roughly 0.2 requests/s; thirty-two concurrent users would wait minutes. Queueing (see `queue-busy-chat-backends`) stops requests from failing but does not add throughput. Decode on these cards is memory-bandwidth-bound, so continuous batching of 2-4 sequences per GPU is the cheapest throughput lever available on this hardware, and batch consumers should yield to interactive ones.

## What Changes

- **Measured multi-slot serving**: qualify `--parallel 2` (and 3-4 where VRAM allows) per chat replica with continuous batching, with the per-slot context reduced accordingly, gated on k6 measurements of aggregate throughput, p95 TTFT and per-stream decode rate under mixed load.
- **Session affinity for cache reuse**: route follow-up turns of one conversation to the same replica (and `id_slot`) so `--cache-reuse` hits; balance only across new sessions. Batch consumers order prompts shared-prefix-first so sequential calls reuse the cache.
- **Priority tiers**: interactive keys get priority over batch keys in LiteLLM's Redis-backed scheduler, so batch work waits when the pool is saturated.
- **Capacity model**: publish per-model-group slot count, measured throughput and the resulting queue-wait table so consumers size their concurrency.

## Capabilities

### New Capabilities

- `chat-concurrency`: multi-slot serving qualification, session affinity, priority scheduling, and published capacity figures.

### Modified Capabilities

- `gpu-inference-availability`: admission bounds and timeouts are derived from the published capacity model.

## Impact

- `gpu-server/config.py` (`MAX_CONCURRENT_REQUESTS`, per-slot context), compose env, `load-tests/` (mixed-load scenarios with TTFT metrics), LiteLLM router (Redis, scheduler, `priority` on keys), an affinity layer (LiteLLM custom routing or a thin router in the wrapper), `docs/load-test-findings.md`.

## Non-goals

- No new hardware or model changes.
- No speculative decoding or KV quantisation below Q8 in this change.
- Embedding, STT and TTS are out of scope except for documenting that embeddings should batch texts per request and TTS needs a reserved slot rather than a queue.
