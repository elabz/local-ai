## Why

HeartCode's `stable-prompt-prefix` change makes chat prompts append-only. Its probe, run directly against `pea-gpu-1` and `pea-gpu-4` on 2026-10-16, measured large prefill savings. Prefill per ordinary turn:

| Route | Today | Append-only |
|---|---|---|
| SFW | 4.5–5 s | ~1.1 s |
| NSFW | 4.3–4.6 s | 0.9 s |

The same change raises HeartCode's context budget to 8192 tokens on both routes (owner decision 2026-10-16). Two things on this side stand in the way:

1. **Routing defeats the cache.** The patched `least-busy` strategy breaks ties between idle replicas uniformly at random. That was the fix for one replica running hot, and it stays. But HeartCode's turns arrive one at a time, so nearly every turn is a tie, and consecutive turns of one conversation land on the same SFW replica only about one time in three. The other replicas hold none of the conversation, so a turn that lands there re-processes the whole prompt.
2. **8K prompts are not qualified on today's runtime.**
   - The 16k slots already reserve the VRAM. But `raise-context-window`'s 2026-07-31 8K runs ended in `llama-server` exits (`-9`, memory-cgroup OOM under older limits), and nothing has been re-measured under the 1,792 MiB chat limit.
   - The host prompt cache (`CACHE_RAM=1024`) holds about 6 cached Gemma prompts at 8K, about 160 MiB each, and only 1–2 Lumimaid prompts, about 540 MiB each at 68 KiB per token.

HeartCode also needs to see whether reuse happens. llama.cpp reports it per request (`timings.cache_n`, `usage.prompt_tokens_details.cached_tokens`), but it is not known whether those figures survive LiteLLM on a streamed response.

## What Changes

- **Session-affine tie-break.**
  - The `least-busy` patch breaks ties by rendezvous hashing of the request's session id over the healthy replicas. An idle pool then sends a conversation to the same replica every time.
  - The least-busy rule still decides under load. A replica leaving the pool moves only its own sessions.
  - Requests with no session id keep the random tie-break.
  - The id reaches the strategy from the request (an `X-Session-Id` header or `metadata.session_id`; task 1.1 decides). This takes over chat affinity from `scale-chat-concurrency` section 2, without a session map.
- **Reuse figures reach consumers.** Prompt-reuse figures from llama.cpp reach the client through LiteLLM on streamed and non-streamed chat completions, or a minimal passthrough is added.
- **8K qualification on both chat routes.**
  - Multi-turn conversations at 8K prompts, through LiteLLM, with VRAM and RSS sampled.
  - A 24-hour soak with zero OOM kills or `llama-server` exits.
  - The gate for HeartCode's 8192 default.
- **`CACHE_RAM` sized for 8K prompts** inside the host memory budget, per route if needed: the NSFW entries are 3.4 times larger. `check-memory-budget.py` stays green.
- **Optional, measured on one Gemma worker before any fleet change:**
  - a lower `--checkpoint-min-step` (default 8,192);
  - `--swa-full`.

  Either would let a prompt changed mid-way reuse the part before the change. Applied only if the measurement shows a benefit within budget.

## Capabilities

### New Capabilities
- `chat-prompt-cache`: session-affine routing for chat model groups, reuse figures visible to consumers, 8K prompt qualification, and host prompt-cache sizing for the qualified prompt size.

### Modified Capabilities
- None at proposal time. If task 4 changes the chat workers' `CACHE_RAM` or `mem_limit`, `host-memory-budget`'s numbers change in config and evidence. Its requirements stay as written.

## Impact

- **LiteLLM:**
  - `litellm/patches/least_busy.py`;
  - possibly a small callback module to carry the session id to the strategy;
  - `gpu-server/tests/test_litellm_least_busy_patch.py`, whose "touches only the tie-break method" guard is widened deliberately;
  - the routing integration test (`gpu-server/tests/integration/`);
  - a LiteLLM `restart` on `.152`, since bind-mounted files never reload on `up -d`.
- **Pea:**
  - `CACHE_RAM` and possibly chat `mem_limit` in `gpu-server/docker-compose.yml` / `models.yaml`;
  - the memory-budget check;
  - a rolling rollout.
- **Evidence:** under this change's `evidence/`.
- **Consumers:** HeartCode sends the session id. Other consumers are unaffected until they send one.
- **Coordination:** HeartCode `stable-prompt-prefix` tasks 5.1–5.5. `scale-chat-concurrency`: its section 2 chat affinity is covered here, and multi-slot serving must keep the tie-break.

## Non-goals

- Multi-slot serving (`scale-chat-concurrency`).
- Changing `--ctx-size` (16,384 stays), the models or the llama.cpp build.
- Prompt layout, which HeartCode owns.
