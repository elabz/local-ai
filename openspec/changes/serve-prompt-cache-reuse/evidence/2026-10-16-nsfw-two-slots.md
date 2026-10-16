# Two resident slots on an NSFW worker (2026-10-16)

- **Question:** at 8K, one Lumimaid worker keeps one conversation in its slot and
  one in the 1 GiB host cache, so a third takes ~30 s
  ([host-cache alternation](2026-10-16-host-cache-alternation.md)). Does a second
  slot raise that without more host RAM?
- **Trial:** `pea-gpu-4` only, through a temporary overlay (`/tmp/parallel-trial.yml`
  on Pea): `MAX_CONCURRENT_REQUESTS=2` (llama-server `--parallel 2`) and
  `N_CTX=18432`. Explicit `--parallel` turns llama.cpp's unified KV off
  (`kv_unified = false`), so each slot is 9,216 tokens, enough for an 8,192 budget
  with margin. `MAX_IN_FLIGHT_REQUESTS` stays 1: the wrapper still admits one
  request at a time, so there is no concurrent decoding and routing is unchanged.
  `CACHE_RAM` stays 1024.
- **VRAM:** 6,587 → 6,717 MiB on the card (+130 MiB).
- **Probe:** `load-tests/prompt_cache_alternation.py --worker :8083 --prompt-tokens 9600
  --rounds 2`, the same settings as the one-slot baseline. Raw: `2026-10-16-alternation-nsfw-7k-parallel2.json`.

| Conversations taking turns | One slot (baseline) | Two slots |
|---:|---:|---:|
| 1 | 0.51 s, 2/2 restored | 0.40 s, 2/2 |
| 2 | 7.11 s, 4/4 (host cache) | **0.41 s, 4/4 (both in slots)** |
| 3 | 30.35 s, 0/6 | **6.49 s, 6/6 (host cache)** |
| 4 | — | 29.57 s, 0/8 |
| 5 | — | 29.79 s, 0/10 |

## Reading

- A worker now keeps **two** ~7.8k-token conversations answering in ~0.4 s, and a
  third comes back from host RAM in ~6.5 s. A fourth re-reads everything (~30 s).
  With three NSFW workers that is ~6 conversations at full speed and ~9 before
  any re-read, against ~3 and ~6 with one slot.
- About half of a host-cache return is the copy out: llama.cpp logs
  `prompt cache update took ~3.2 s` for a ~520 MiB entry. The cards sit on
  PCIe 1.0 x1 links.
- llama.cpp picked the right slot for each return (`cache_n` ≈ the whole prompt
  on every 2-conversation return).

## Output check

Greedy replies from the two-slot worker against one-slot `:8085`
(`compare.py`-style, temperature 0, two requests per size):

- 632 and 8,252 prompt tokens: identical, request for request.
- 4,161 tokens: both coherent and each self-consistent, but they differed on a near tie
  ("Corwin, 18 entries" against "Rook, 19 of 187"). Likely cause: a different
  context size changes the order in which llama.cpp sums the attention terms, which
  can flip a low-margin token. This is unproven, and it is not corruption.

## Status

Trial only: the controller restores the production settings if it ever recreates
the slot. Making it permanent for the NSFW group means moving `MAX_CONCURRENT_REQUESTS`
and `N_CTX` into per-worker settings (`models.yaml` `server:` → `models.generated.env`)
and rolling out with the rolling-rollout procedure (4.3). That needs the owner's go-ahead.
