# Host prompt cache at ~7.4k-token prompts (2026-10-16)

- **Probe:** `load-tests/prompt_cache_alternation.py`, run straight against one worker's wrapper.
- **Method:** K conversations take turns, so each return finds its prompt evicted from the single slot. A return either is restored from llama.cpp's host cache (`--cache-ram 1024`, today's value) or re-evaluates the whole prompt.
- **Runtime:** `CACHE_RAM=1024`, `mem_limit 1792m`, q8_0 KV, b10566, after the 6cd056c rollout.

| Route (worker) | Prompt | K | Restored | Median return (wall) |
|---|---:|---:|---:|---:|
| SFW, Gemma 4 E4B (`pea-gpu-3`) | ~7,346 | 2 | 4/4 | 1.77 s |
| | | 4 | 8/8 | 1.81 s |
| | | 6 | 12/12 | 1.70 s |
| | | 8 | 16/16 | 1.53 s |
| NSFW, Lumimaid 8B (`pea-gpu-4`) | ~7,849 | 1 | 2/2 (still in the slot) | 0.51 s |
| | | 2 | 4/4 | 7.11 s |
| | | 3 | **0/6** | **30.35 s** |

An earlier SFW run at ~5,700 tokens restored 12/12 at K=4 (1.35 s); the slot itself answered in 0.56 s.

## Reading

- **SFW is fine at 8K with today's 1 GiB.** Gemma's sliding-window cache is small: an entry is ~50–60 MiB at 3k tokens. At least 8 conversations per worker come back in under 2 s.
- **NSFW is not.**
  - **The cost.** Lumimaid's KV is 68 KiB per token at q8_0, so ~520 MiB at 7.8k. 1 GiB holds one evicted conversation besides the one in the slot.
  - **Restoring is slow.** It moves ~0.5 GB back to the card, ~7 s here; the cards sit on narrow PCIe links.
  - **A third conversation evicts it outright.** It then pays a full re-evaluation, ~30 s at ~260 prompt tokens/s.
- **What it means for HeartCode's 8K gate.** With more NSFW conversations active than there are NSFW replicas, returning turns at 8K would often take 7–30 s. Even ordinary turns would, wherever affinity cannot keep a conversation alone on its worker.
  - A full NSFW rebuild turn of ~4.5k tokens would take ~17 s.
  - SFW at ~2.1 ms/token would take ~9 s.

## Options for §4.2 (owner's call: they change fleet memory settings)

1. **Raise NSFW `CACHE_RAM`.** At ~520 MiB per conversation, each extra conversation kept needs another ~520 MiB per worker. The host budget (29,975 MiB, 29,376 allocated) has ~600 MiB spare in total. Raising it means trimming other services' limits.
2. **Keep NSFW at a smaller budget** (e.g. 4096–6144) while SFW goes to 8192. HeartCode's budgets are already per route (`CONTEXT_BUDGET_SFW` / `_NSFW`).
3. **Accept slower returning turns on NSFW at 8K,** and rely on affinity plus light concurrency until there are more NSFW replicas.

Recommendation: option 2 for now, SFW 8192 and NSFW 4096, measured again in §3.2. Revisit NSFW once the host budget or replica count changes.
