## 1. Session-affine tie-break

- [x] 1.1 Read the pinned LiteLLM image's router and proxy code to settle how a session id reaches `least_busy.py` (D2): a contextvar set by a pre-call callback, or `request_kwargs` through the router call. Choose `X-Session-Id` or `metadata.session_id`, record the choice in design D2, and tell HeartCode (`stable-prompt-prefix` 2.8).
  *Done 2026-10-16: a filter callback plus a context variable; both the header and `metadata.session_id` are accepted (design D2).*
- [x] 1.2 Implement rendezvous hashing among the least-busy healthy ties in `litellm/patches/least_busy.py` (D1), plus the callback if 1.1 chose it. Keep the random tie-break when no id is present.
  *Done 2026-10-16: `litellm/session_affinity.py` (registered in `config.base.yaml`, mounted in compose) and the tie-break in `patches/least_busy.py`.*
- [x] 1.3 Unit tests in `gpu-server/tests/test_litellm_least_busy_patch.py`:
  - same id, same replica when idle;
  - a busy preferred replica is skipped;
  - removing a replica moves only its sessions;
  - no id still spreads.

  Widen the "touches only the tie-break method" guard to name exactly the changed methods.
  *Done 2026-10-16: 4 tie-break tests and 10 callback tests. The CI guard needed no widening, since the change stays inside `_get_available_deployments`.*
- [x] 1.4 Extend the pinned-LiteLLM routing integration test (`gpu-server/tests/integration/`) so that a request carrying the id through the real proxy reaches the same fake backend repeatedly.
  *Done 2026-10-16: the rig now mounts the production patch and callback, and adds three named chat replicas. 17/17 pass, including: a session keeps one replica over 12 requests (header and metadata forms), and distinct and anonymous requests still spread over all three. Before the callback was registered, the affinity test failed, so it is a real check.*
- [x] 1.5 Deploy to `.152` (`docker compose restart`; verify the mounted file is the one the proxy imports). Then, with HeartCode sending the id, confirm consecutive turns of one conversation land on one replica.
  *Done 2026-10-16 (`evidence/2026-10-16-affinity-rollout.md`):*
  - *LiteLLM was recreated on `.152` and loads `session_affinity`;*
  - *sessions 2 s apart stayed on one replica, 18/18;*
  - *HeartCode sends `X-Session-Id` on its routes (HeartCode ad67bc27);*
  - *requests sent back to back can stray while the previous request's in-flight count is still being decremented.*
- [ ] 1.6 Compare the 24-hour per-replica split before and after on both chat groups (2026-09-18 baseline: 1008/318/6).
- [x] 1.7 Update `litellm/patches/README.md` and CLAUDE.md's routing notes. Note in `scale-chat-concurrency` that its §2 chat affinity is implemented here.
  *Done 2026-10-16.*

## 2. Reuse figures through LiteLLM

- [x] 2.1 Send one streamed and one non-streamed completion per chat route through LiteLLM. Record whether `usage.prompt_tokens_details.cached_tokens` or `timings` arrives (D3).
  *Done 2026-10-16, against the live fleet:*
  - *Non-streamed replies carry `usage.prompt_tokens_details.cached_tokens` and `timings` through LiteLLM.*
  - *Streamed replies carry neither. llama-server sends both in its final chunk, but the Pea wrapper rebuilt the stream from content deltas and dropped it.*
  - *The rig confirmed that the pinned LiteLLM forwards `stream_options` to the backend and passes `cached_tokens` back to the client.*
- [x] 2.2 If neither arrives on streams, add the smallest passthrough (a setting, then the wrapper, then a patch), with a test.
  *Code done 2026-10-16:*
  - *the wrapper asks llama-server for usage on every stream and keeps it;*
  - *when the client asked (`stream_options.include_usage`), it sends OpenAI's final no-choices usage chunk, with `timings` too;*
  - *tests in `tests/test_chat_stream_usage.py`.*

  *Live 2026-10-16: rolled to all six chat workers, after a fix for Lumimaid, which reports reuse only in `timings` (6cd056c). Streamed replies through LiteLLM now carry `cached_tokens` on both routes.*

## 3. 8K qualification (gate for HeartCode's 8192 default)

- [x] 3.1 Build or adapt the driver for multi-turn conversations whose prompts grow to ~7.4k tokens with periodic rebuilds, plus exact-token 8K requests, through LiteLLM with affinity on. Sample VRAM, RSS and kernel OOM events. HeartCode's `backend/scripts/measure_context_window.py` is the starting point.
  *Done 2026-10-16: `load-tests/prompt_cache_conversations.py` (append-only conversations to a budget with rebuilds, through LiteLLM with affinity; it samples VRAM, container memory, restarts and kernel OOM kills). `load-tests/prompt_cache_alternation.py` serves §4.*
- [x] 3.2 Run it on one SFW and one NSFW worker. Record VRAM headroom, peak RSS against `mem_limit`, and first-token time for cached and rebuild turns.
  *Done 2026-10-16 (`evidence/2026-10-16-8k-conversations.md`):*
  - *0 errors, exits or OOM kills on both routes; lowest headroom 457 MiB;*
  - *ordinary-turn first token: SFW p95 2.83–3.18 s, NSFW 3.68 s;*
  - *rebuild: SFW 10.7 s (Gemma cannot shift its cache), NSFW 6.8 s;*
  - *same replica 188/190.*
- [ ] 3.3 Run a 24-hour soak at a representative mix on both groups. Pass: zero failures, zero `llama-server` exits, zero OOM kills, headroom held (D4).
- [ ] 3.4 Record the evidence and the decision. Tell HeartCode (`stable-prompt-prefix` 5.3).

## 4. Host prompt cache for 8K prompts

- [x] 4.1 Measure host-cache entry sizes at 8K on both routes, and returning-conversation TTFT with 2–4 alternating sessions per worker, at `CACHE_RAM` 1024 and larger candidates, using `host-memory-budget`'s method.
  *Done 2026-10-16 at today's `CACHE_RAM=1024` (`evidence/2026-10-16-host-cache-alternation.md`):*
  - *SFW at ~7.35k: 8 alternating conversations, all restored in ~1.5–1.8 s;*
  - *NSFW at ~7.8k: 2 restored in ~7 s, 3 not at all (~30 s full re-evaluation).*

  *Larger values were not tried, since that changes fleet memory settings and is the owner's call (4.2).*
- [ ] 4.2 Choose `CACHE_RAM` per route (D5). If a `mem_limit` must grow, rebalance the budget so `check-memory-budget.py` passes. Settle whether per-route values need a `models.yaml` / `render-config.py` change.
  - _2026-10-16 progress:_ a second slot on `pea-gpu-4` (`--parallel 2`, `N_CTX=18432`, +130 MiB VRAM, `CACHE_RAM` unchanged) kept 2 conversations at 0.4 s and brought a 3rd back in 6.5 s, against 7.1 s and 30 s with one slot ([evidence](evidence/2026-10-16-nsfw-two-slots.md)). That removes the need for a larger NSFW `CACHE_RAM`. The NSFW rollout of two slots awaits the owner.
- [ ] 4.3 Roll out through the rolling-rollout procedure. Verify the command lines and the plateau.

## 5. Optional: checkpoint flags on Gemma

- [ ] 5.1 On one Gemma worker, measure `--checkpoint-min-step` at 256, 512 and 1024: checkpoint memory, and reuse after a mid-prompt change (an edited earlier message, a rebuild that keeps the persona).
- [ ] 5.2 Measure `--swa-full`: VRAM, and the same reuse cases.
- [ ] 5.3 Decide. Apply to the SFW group only with evidence (requirement "Checkpoint flags change only after isolated measurement"), or record why not.
