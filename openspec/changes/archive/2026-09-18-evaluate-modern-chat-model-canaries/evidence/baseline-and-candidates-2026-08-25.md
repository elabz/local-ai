# Baseline and candidate admission — 2026-08-25

## Safe Pea baseline

- Host memory: 31 GiB total, 23 GiB available; swap 15 GiB total, 169 MiB used.
- All current chat, text-embedding, vision/DINO embedding, image, and speech services were healthy.
- Relevant chat and embedding containers had zero Docker restarts since the host restart.
- Current single-request decode samples: Stheno 8B Q5 approximately 25.6 t/s; Lumimaid 8B Q5 approximately 25.8 t/s; Qwen3 8B Q4 approximately 26.1 t/s.
- GPU 4 retains Lumimaid plus the surviving text-embedding control. GPU 3 retains the surviving DINO replica while GPU 6 is evaluated.

## Runtime identity

- Normal chat image: llama.cpp build 8027, commit `25224c802`.
- Canary image: llama.cpp build 10566, commit `bb4caa754`.
- The repository Dockerfile now pins `bb4caa754` instead of cloning mutable `main`.

## Admitted candidates

| Role | Model | Quant | Admission rationale |
|---|---|---|---|
| SFW primary | `ggml-org/gemma-3-12b-it-GGUF` | Q4_K_M | Official llama.cpp GGUF, 7.3 GB, materially larger capacity; requires dedicated GPU and progressive context proof. |
| SFW fallback | `ggml-org/gemma-3-4b-it-GGUF` | Q8_0 | Official llama.cpp GGUF, high-fidelity quant, comfortable 8 GiB fit if 12B fails. |
| NSFW challenger | `huihui-ai/Huihui-Qwen3-8B-abliterated-v2`, GGUF by Medvedko | Q5_K_M | Apache-2.0 Qwen3-8B base, documented abliteration method, 5.85 GB artifact, and footprint comparable to current Lumimaid. |

The NSFW candidate is admitted for private evaluation only. Abliteration is not evidence of roleplay quality or safety; the fixed comparison suite determines selection.

## 2026 NSFW/RP shortlist revision — 2026-08-27

The Huihui Qwen3 candidate remains valid historical mechanical evidence but is no longer the selection target because the desired product mode is direct response without a thinking phase. The replacement shortlist is:

| Evaluation role | Model | Quant | Admission rationale |
|---|---|---|---|
| RP specialist | `rpDungeon/Gemma-4-E4B-Luchador`, GGUF by Bartowski | Q5_K_M | Gemma 4 release, documented RP/creative-writing training and thinking-off evaluation, 5.82 GB artifact with usable KV headroom. |
| Capacity challenger | `HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced` | Q4_K_M | Gemma 4 12B QAT, 6.9 GB-class artifact, newer capacity tier that requires progressive 8 GiB qualification. |
| Refusal-free control | `HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive` | Q6_K_P | Gemma 4 E4B uncensored control, 5.9 GB-class artifact, comfortable direct-response fit. |

All candidates are private-evaluation only, use no multimodal projector, and run with native reasoning disabled. Model-card claims do not satisfy the fixed quality, allowed-adult refusal, prohibited-content, provenance, or live Pea gates.
