# NSFW Gemma 4 rerun and blind prose packet — 2026-09-04

This closes the machine-scorable part of task 4.4. It reruns the surviving
2026 challenger, `rpDungeon/Gemma-4-E4B-Luchador` Q5_K_M, and the GPU 4
Lumimaid control on the current slot settings and a re-created fixed suite,
and it produces the provider-blind prose packet that the qualitative gate
requires a human to score. The two rejected challengers (Gemma4 12B Balanced,
Gemma 4 E4B Aggressive) were not rerun; their 2026-08-29 rejections stand on
direct-response and prohibited-content failures that a rerun cannot cure.

## Fixed suite version change

Version 1.1.0 of the private suite (SHA-256 `23fe5d17…`) was not retained on
any host, so the suite was re-created as version 1.2.0 with the same six case
ids and categories (`slow-burn-romance`, `permitted-adult`, `strong-persona`,
`lore-heavy`, `dialogue-only`, `descriptive-style`) and the same two
prohibited-content probes. It lives outside git on Pea under the operator's
private canary directory; only its SHA-256
(`ab800a9c4103ee22f0e97554269dce47372da10d5bc9435f7c33f1c89d6beae9`) and
aggregate results are recorded here. Version 1.2.0 additionally declares
mechanical style checks per case (sentence caps, contraction bans, required
lore tokens, dialogue-only and no-dialogue formatting) that the blind packet
builder scores without exposing prose.

## Runtime

- Luchador: `pea-nsfw-model-canary-gpu6`, port 18086, GPU 6
  (`GPU-fe0fc635`), pinned llama.cpp build 10566 (`bb4caa754`), 4,096 context,
  Q8 KV, one slot, cache reuse 256, reasoning off, embedded Gemma 4 template.
  This is the configuration HeartCode's NSFW canary slot runs.
- Lumimaid control: production `pea-gpu-4`, port 8083, GPU 4, unchanged.
- The GPU 5 SFW canary was serving the Gemma 3 benchmark at the same time; the
  Pea host has two CPU cores, so the throughput figures below are, if anything,
  conservative.

## Results

| Gate | Luchador Q5_K_M (GPU 6) | Lumimaid control (GPU 4) |
|---|---|---|
| Decode p10 / median / mean at 4K, ~3.6K-token prompt, 10 requests | **19.37 / 19.70 / 19.66 t/s** (floor 12, pass; prompt 57.6 t/s) | production control, not re-measured |
| Direct response, retrieval, native JSON schema | pass | existing production API |
| Multi-turn tool call | fail (empty answer after the tool result, as on 2026-08-29) | n/a |
| Fixed suite v1.2.0, 11 responses | 0 blank, 0 reasoning leaks, 0 permitted-adult refusals, 2/2 prohibited refusals, mechanical pass | same: 0 / 0 / 0 / 2/2, mechanical pass |
| Blind packet style checks (9 turns per arm) | 14/14 passed | 14/14 passed |

Files: `luchador-4k-benchmark-2026-09-04.json`, `luchador-4k-compat-2026-09-04.json`,
`luchador-quality-v1.2.0-2026-09-04.json`,
`lumimaid-control-quality-v1.2.0-2026-09-04.json`,
`blind-packet-public-2026-09-04.json`.

The 4K throughput is slightly below the 20.2 t/s recorded on 2026-08-29 and
the 21.9 t/s HeartCode measured through LiteLLM, consistent with the
concurrent GPU 5 load; it clears the 12 t/s NSFW floor by a wide margin.

## Blind prose packet

`gpu-server/scripts/model_canary_blind_packet.py` played all six cases against
both arms with the suite's samplers (temperature 1.0, top-p 0.95, top-k 64,
repeat penalty 1.0, 384 tokens) and assigned the labels A/B per case from a
seeded shuffle. The full transcripts and the answer key are only in the private
packet on Pea (`blind-packet-private.json`, mode 0600) with a rendered
Markdown review sheet next to it. The repository copy carries case ids,
per-turn SHA-256 hashes, lengths, decode speeds, style-check outcomes, and the
SHA-256 of the answer key
(`blind-packet-public-2026-09-04.json`), so a reviewer's scores can later be
reconciled against the key without publishing prose.

## What remains human

Score both arms per case from 1 to 5 on character fidelity, naturalness,
repetition, prose quality, and tone fit before opening the answer key. The
qualitative gate, and therefore any promotion of Luchador, stays open until
those scores are recorded. The product owner also still has to decide whether
native multi-turn tool calls are required on the NSFW route, because Luchador
fails that probe on the pinned build.
