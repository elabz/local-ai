## Context

- **Chat workers:**
  - `pea-gpu-1..3` serve SFW (Gemma 4 E4B QAT Q4_0, sliding-window attention);
  - `pea-gpu-4..6` serve NSFW (Lumimaid v0.2 8B, full attention);
  - each runs `llama-server` b10566 with `--parallel 1 --ctx-size 16384 --cache-reuse 256 --cache-ram 1024`, q8_0 KV and a 1,792 MiB `mem_limit`.
- **Routing:** LiteLLM on `.152` with `routing_strategy: least-busy` and the local tie-break patch (`litellm/patches/README.md`).
  - The strategy's selection gets `model_group` and `healthy_deployments` only; it never sees the request.
  - CI pins the patch to the image digest and checks that only the tie-break method differs from upstream.
- **HeartCode's evidence** (`../heartcode/openspec/changes/stable-prompt-prefix/evidence/2026-10-16-cache-probe/`):
  - Gemma reuses its cache up to the start of the previous request's last message, so HeartCode moves everything that changes per turn into that message;
  - reuse needs the next turn to land on the same worker.
- **From the worker logs on 2026-10-16:**
  - Gemma's host-cache entries are 50–63 MiB for ~3k-token prompts (≈20 KiB per token);
  - Lumimaid's KV is 1,088 MiB for 16,384 cells (68 KiB per token at q8_0), and saving a prompt to the host cache took ~270 ms.

## Goals / Non-Goals

**Goals:**
- **Affinity.** Consecutive turns of a conversation reach the same replica whenever the pool allows it, without hurting load spread or failover.
- **Visibility.** HeartCode can see per-request reuse on streamed responses.
- **8K prompts are safe** on both routes under today's memory limits.
- **The host cache is sized** for the 8K prompt size within `host-memory-budget`.

**Non-Goals:**
- A session store, slot pinning (`id_slot`), or multi-slot serving.
- Any change to prompt layout, models, the build or `--ctx-size`.

## Decisions

### D1. Rendezvous hashing, applied only to ties
Among the healthy deployments with the lowest in-flight count, pick the one with the highest `hash(session_id, deployment_id)`. With no session id, pick at random, as today.

- **Why hashing and not a map:**
  - It needs no state, no TTL and no Redis.
  - In an idle pool, the same conversation always gets the same replica.
  - When a replica becomes unhealthy, only the sessions that hashed to it move. When it comes back, they return.
- **Why ties only:** the least-busy rule keeps deciding under load, so affinity never makes a request wait behind a busy replica. It also keeps the hot-replica fix: distinct conversations still spread, because their hashes differ.
- **Alternatives:**
  - **A Redis session→deployment map** (`scale-chat-concurrency` D2). Stateful, with TTL tuning, and it only adds "stick even when busier", which is the wrong trade at one slot per worker.
  - **`id_slot` pinning.** Meaningless at `--parallel 1`.
  - **Per-replica model aliases chosen by the client.** That duplicates health and load logic in every consumer.
  - **LiteLLM's `prompt_caching` pre-call check.** Aimed at provider-side caching. Unverified for self-hosted deployments.

### D2. Getting the session id to the strategy
The strategy's `_get_available_deployments` never sees the request. Task 1.1 reads the pinned image's router and proxy to find the smallest path. The candidates, in order of preference:
1. **A contextvar set by a proxy pre-call callback.** The callback reads `X-Session-Id` from the request headers, or `metadata.session_id` from the body. `least_busy.py` reads the contextvar. The router is untouched, provided the callback and the routing run in the same task context, which 1.1 confirms.
2. **Extending the patched `async_get_available_deployments` call** to receive `request_kwargs`. This touches the router call site too, so it is a larger patch to carry across image bumps.

Whichever form works is what HeartCode sends (its task 2.8). The CI guard on the patch is widened to name exactly the methods that change.

### D3. Reuse figures
Task 2.1 sends one streamed and one non-streamed completion through LiteLLM on each route and records which of these arrive:
- `timings` (llama.cpp's own field);
- `usage.prompt_tokens_details.cached_tokens`.

If `cached_tokens` arrives in the final chunk's usage, nothing changes here. If not, the smallest fix wins, in this order:
- a LiteLLM setting;
- a passthrough in the wrapper's response;
- a patch.

### D4. 8K qualification uses real conversations, not just exact-token requests
`raise-context-window` measured single exact-8K requests. With the append-only layout, an 8K prompt is mostly cached, and the full-cost moment is HeartCode's rebuild turn (about 4.5k tokens evaluated).

The qualification therefore runs:
- **multi-turn conversations** whose prompts grow to ~7.4k tokens (8192 minus HeartCode's response buffer), with rebuilds, through LiteLLM with affinity on;
- **plus** the exact-token worst case.

Both are sampled for VRAM, RSS and OOM events. The gate is `raise-context-window`'s, updated:
- zero failed requests or `llama-server` exits;
- ≥ 300 MiB VRAM headroom;
- RSS below `mem_limit` with the host cache full;
- a 24-hour soak at a representative mix.

### D5. `CACHE_RAM` per route if the numbers require it
At 8K, a Lumimaid entry is ~540 MiB. The current 1,024 MiB keeps 1–2 conversations, so a conversation evicted from the slot by another user's turn can be restored only if it is one of those 1–2.

With affinity, the slot itself holds the conversation most of the time. The host cache then matters only when replicas are shared.

Task 4 measures returning-conversation TTFT at 2–4 alternating sessions per worker under `host-memory-budget`'s method. It then picks the smallest `CACHE_RAM` that keeps the benefit. A per-route value is allowed. Any `mem_limit` increase must fit the budget by trimming elsewhere, exactly as `check-memory-budget.py` enforces.

### D6. Checkpoint flags are optional and measured in isolation
`--checkpoint-min-step` (default 8,192) controls how often llama.cpp saves sliding-window checkpoints mid-prompt.
- **What a lower value buys:** a prompt that changes in the middle (an edited message, a HeartCode rebuild that keeps the persona) could resume from the last checkpoint instead of from zero.
- **What it costs:** checkpoint memory per slot, which lives in host RAM inside the same `mem_limit`.

`--swa-full` gives the sliding-window layers a full-size cache, trading VRAM for arbitrary reuse.

Both are measured on one Gemma worker only. Neither is required for HeartCode's main gain, which was measured with today's flags.

## Risks / Trade-offs

- **[Affinity reconcentrates load on one replica]** → it applies only to ties, and distinct sessions hash to different replicas. The 24-hour per-replica request split is compared before and after (the 2026-09-18 baseline was 1008/318/6).
- **[The contextvar does not survive into the routing call]** → the integration test catches it (task 1.4). The fallback is D2's option 2.
- **[A larger patch is harder to carry across LiteLLM bumps]** → the upstream copy stays beside it, and the CI guard names the changed methods.
- **[8K prompts push RSS past `mem_limit`]** → a soak before any default changes. HeartCode can keep 4096 with the new layout if 8K fails.
- **[Session ids are user data]** → the id is HeartCode's opaque conversation UUID. It is used only for hashing, never logged with content, and not persisted.

## Migration Plan

1. Tie-break patch, callback and tests (§1). Deploy with `docker compose restart` of LiteLLM on `.152`. With no session ids sent yet, behaviour is identical.
2. HeartCode starts sending the id. Verify consecutive turns on one replica (§1.5).
3. Reuse figures (§2) and 8K qualification (§3), then `CACHE_RAM` (§4) through the rolling-rollout procedure.
4. **Rollback:**
   - Restore the previous `least_busy.py` and restart LiteLLM.
   - `CACHE_RAM` and limits revert through compose.
   - HeartCode keeps sending the id harmlessly.

## Open Questions

- **The session id's path** (D2): settled by task 1.1.
- **Per-route `CACHE_RAM`:** does it need a schema change in `models.yaml` / `render-config.py`, or is a per-service override enough?
