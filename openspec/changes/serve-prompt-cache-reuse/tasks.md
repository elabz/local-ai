## 1. Session-affine tie-break

- [ ] 1.1 Read the pinned LiteLLM image's router and proxy code to settle how a session id reaches `least_busy.py` (D2): a contextvar set by a pre-call callback, or `request_kwargs` through the router call. Choose `X-Session-Id` or `metadata.session_id`, record the choice in design D2, and tell HeartCode (`stable-prompt-prefix` 2.8).
- [ ] 1.2 Implement rendezvous hashing among the least-busy healthy ties in `litellm/patches/least_busy.py` (D1), plus the callback if 1.1 chose it. Keep the random tie-break when no id is present.
- [ ] 1.3 Unit tests in `gpu-server/tests/test_litellm_least_busy_patch.py`:
  - same id, same replica when idle;
  - a busy preferred replica is skipped;
  - removing a replica moves only its sessions;
  - no id still spreads.

  Widen the "touches only the tie-break method" guard to name exactly the changed methods.
- [ ] 1.4 Extend the pinned-LiteLLM routing integration test (`gpu-server/tests/integration/`) so that a request carrying the id through the real proxy reaches the same fake backend repeatedly.
- [ ] 1.5 Deploy to `.152` (`docker compose restart`; verify the mounted file is the one the proxy imports). Then, with HeartCode sending the id, confirm consecutive turns of one conversation land on one replica.
- [ ] 1.6 Compare the 24-hour per-replica split before and after on both chat groups (2026-09-18 baseline: 1008/318/6).
- [ ] 1.7 Update `litellm/patches/README.md` and CLAUDE.md's routing notes. Note in `scale-chat-concurrency` that its §2 chat affinity is implemented here.

## 2. Reuse figures through LiteLLM

- [ ] 2.1 Send one streamed and one non-streamed completion per chat route through LiteLLM. Record whether `usage.prompt_tokens_details.cached_tokens` or `timings` arrives (D3).
- [ ] 2.2 If neither arrives on streams, add the smallest passthrough (a setting, then the wrapper, then a patch), with a test.

## 3. 8K qualification (gate for HeartCode's 8192 default)

- [ ] 3.1 Build or adapt the driver for multi-turn conversations whose prompts grow to ~7.4k tokens with periodic rebuilds, plus exact-token 8K requests, through LiteLLM with affinity on. Sample VRAM, RSS and kernel OOM events. HeartCode's `backend/scripts/measure_context_window.py` is the starting point.
- [ ] 3.2 Run it on one SFW and one NSFW worker. Record VRAM headroom, peak RSS against `mem_limit`, and first-token time for cached and rebuild turns.
- [ ] 3.3 Run a 24-hour soak at a representative mix on both groups. Pass: zero failures, zero `llama-server` exits, zero OOM kills, headroom held (D4).
- [ ] 3.4 Record the evidence and the decision. Tell HeartCode (`stable-prompt-prefix` 5.3).

## 4. Host prompt cache for 8K prompts

- [ ] 4.1 Measure host-cache entry sizes at 8K on both routes, and returning-conversation TTFT with 2–4 alternating sessions per worker, at `CACHE_RAM` 1024 and larger candidates, using `host-memory-budget`'s method.
- [ ] 4.2 Choose `CACHE_RAM` per route (D5). If a `mem_limit` must grow, rebalance the budget so `check-memory-budget.py` passes. Settle whether per-route values need a `models.yaml` / `render-config.py` change.
- [ ] 4.3 Roll out through the rolling-rollout procedure. Verify the command lines and the plateau.

## 5. Optional: checkpoint flags on Gemma

- [ ] 5.1 On one Gemma worker, measure `--checkpoint-min-step` at 256, 512 and 1024: checkpoint memory, and reuse after a mid-prompt change (an edited earlier message, a rebuild that keeps the persona).
- [ ] 5.2 Measure `--swa-full`: VRAM, and the same reuse cases.
- [ ] 5.3 Decide. Apply to the SFW group only with evidence (requirement "Checkpoint flags change only after isolated measurement"), or record why not.
