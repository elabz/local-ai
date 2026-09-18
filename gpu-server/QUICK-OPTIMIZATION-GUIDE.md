# Pea LLM Optimization Quick Guide

Last updated: 2026-09-04

For rationale, evidence, candidate links, and the complete test matrix, use
[`OPTIMIZATION-ANALYSIS.md`](OPTIMIZATION-ANALYSIS.md).

## Safe starting configuration

- One slot; full GPU offload.
- Target route context from the start: 16K for SFW, proposed production context
  for NSFW.
- Batch 128, micro-batch 64, two CPU threads, Q8 K/V cache.
- No multimodal projector for text-only chat.
- No speculative decoding or model-native MTP during initial qualification.
- Pin the llama.cpp image and exact GGUF revision/SHA-256.

GPU 5 must remain comfortably below the observed corruption region around
7.6 GiB. Qualify on GPU 6 first and verify repeated coherent generation, not
only successful model loading.

## Current canary queue

| Route | Priority | Candidate | Initial quant |
|---|---:|---|---|
| SFW | 1 | Qwen3.5-9B | Q4_K_M, 6.17 GB |
| SFW | 2 | Ministral-3-8B-Instruct-2512 | Q5_K_M, 6.06 GB |
| SFW | 3 | Meta-Llama-3.1-8B-Instruct | Q5_K_M, 5.73 GB |
| NSFW | baseline | Gemma-4-E4B-Luchador | existing Q5_K_M |
| NSFW | 1 | Gemma-4-E4B-Luchador-Rudo | Q5_K_M, 5.76 GB |
| NSFW | 2 | Nyx-RP-9B-Instruct-2608-v1 | Q4_K_M, 5.78 GB |
| NSFW | 3 | Interferon-gamma RP 9B preview | defer; Q4_K_M |

## Per-candidate checks

1. Record provenance, immutable revision, filename, size, and digest.
2. Record idle and peak VRAM, host RSS, temperature, and startup warnings.
3. Run repeated direct-response probes, streaming, JSON/schema, retrieval, and
   single-/multi-turn tool checks before long benchmarks.
4. Compare cold and warm TTFT, prompt rate, and decode p10/median.
5. Run the production-prompt SFW or NSFW quality/safety suite.
6. Run blind prose review for NSFW finalists.
7. Soak under concurrent host load, restore displaced services, and verify
   public aliases remain unchanged unless promotion is approved.

Do not assume that a larger batch, micro-batch, cache-reuse value, newer
runtime, or higher-bit quant is faster or safer. Change one variable at a time
and retain the measured rollback configuration.
