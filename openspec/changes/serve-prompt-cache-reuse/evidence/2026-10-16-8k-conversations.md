# 8K append-only conversations through LiteLLM (§3.2, 2026-10-16)

- **Driver:** `load-tests/prompt_cache_conversations.py`.
- **Prompt shape:**
  - a ~1.5k-token frame;
  - a history that only grows;
  - a ~550-token per-turn memory block in the final user message;
  - replies up to 250 tokens.
- **Rebuild rule:** when the next turn would pass 8192 − 819, the history is cut to the newest messages within half the room.
- **Session:** each conversation sends `X-Session-Id`.
- **Sampling:** Pea every 10–15 s.
- **Runtime:** the 6cd056c fleet, `CACHE_RAM=1024`, q8_0 KV, 16k slots, LiteLLM with session affinity.

| | SFW, 2 × 30 turns | SFW, 1 × 75 turns | NSFW, 2 × 30 turns |
|---|---|---|---|
| Errors | 0 | 0 | 0 |
| Largest prompt | 4,773 | 7,274 | 7,130 |
| Rebuild turns | 0 | 1 | 2 |
| Ordinary first token p50 / p95 | 2.16 / 2.83 s | 2.52 / 3.18 s | 3.04 / 3.68 s |
| Ordinary turns above 6k: p50 / max | — | 2.90 / 3.69 s | — |
| Rebuild first token | — | 10.68 s | p50 6.41 / p95 6.76 s |
| Reuse on ordinary turns | 79% | 87% | 87% |
| Evaluated tokens per ordinary turn (median) | 621 | 648 | 574 |
| Consecutive turns on one replica | 58/58 | 74/74 | 56/58 |
| Lowest VRAM headroom (any card) | 475 MiB | 457 MiB | 457 MiB |
| Container restarts or `llama-server` exits | none | none | none |
| Kernel OOM kills | 0 | 0 | 0 |

## Reading against the gate (HeartCode `stable-prompt-prefix` D10)

- **Safety holds on both routes.** No failures, exits or OOM kills, and headroom stays above the 300 MiB floor; the tightest card was 457 MiB.
  - The 2026-07-31 `-9` exits of `raise-context-window` did not recur under today's limits.
  - This is a short run, not the 24-hour soak (§3.3).
- **Ordinary turns:**
  - NSFW is well inside its 5 s target.
  - SFW is at its 3 s target: p95 2.83 s for prompts up to ~4.8k, but 3.18 s across the long run, with turns above 6k at p50 2.9 s.
  - What each turn evaluates is the per-turn block plus the previous reply (~650 tokens). HeartCode's lever is the retrieval allocation, which is the bulk of that block.
- **Rebuild turns:**
  - NSFW rebuilds are cheap, 6.4–6.8 s. Lumimaid's full attention lets `--cache-reuse` keep the unchanged frame.
  - The SFW rebuild re-evaluated everything, 10.7 s. Gemma's sliding-window cache cannot be shifted, and checkpoints are 8,192 tokens apart.
  - §5 (a lower `--checkpoint-min-step`) is the lever that would let a Gemma rebuild keep the frame. HeartCode's levers are a lower keep share and a smaller frame.
- **Not shown here:** contention. One conversation per worker is the easy case. The §4 alternation probe covers sharing: NSFW at ~7.8k loses a third conversation from its host cache, ~30 s.
