## Why

Pea's upgraded host memory reduces host-level OOM pressure and creates an opportunity to replace the aging SFW and NSFW chat models with stronger modern candidates. Selection must be based on reproducible, workload-relevant quality and context-window evidence while preserving the minimum decode throughput required by HeartCode.

## What Changes

- Add a reproducible canary evaluation workflow for modern GGUF chat models on Pea's 8 GiB P104-100 GPUs.
- Evaluate Gemma 3 12B Instruct Q4_K_M as the preferred SFW candidate, with Gemma 3 4B Instruct Q8_0 as the fallback.
- Reassign GPU 5 from the Qwen3 canary to the Gemma SFW canary and temporarily stop one co-located text-embedding replica.
- Evaluate a 2026 Gemma 4 NSFW/RP shortlist on GPU 6 while retaining GPU 4's Lumimaid deployment as the simultaneous control; temporarily stop the co-located DINO replica on GPU 6.
- Run `rpDungeon/Gemma-4-E4B-Luchador` Q5_K_M as the RP specialist, `HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced` Q4_K_M as the capacity challenger, and `HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive` Q6_K_P as the refusal-free control, all with native reasoning disabled.
- Measure context configurations progressively at 4K, 8K, 16K, 24K, and 32K where feasible, with 16K as the SFW hard gate.
- Gate SFW selection on p10 decode throughput of at least 10 tokens/second at 16K and NSFW selection on at least 12 tokens/second at its selected production context.
- Score the frozen site-2017 tool-demand workload for SFW schema fidelity, safety, evidence grounding, latency, and throughput, then use the winning model for the outstanding failed-call mop-up only after qualification.
- Record model source, exact artifact digest, quantization, llama.cpp build, launch parameters, GPU placement, and benchmark evidence without exposing prompts or private corpus content.

## Capabilities

### New Capabilities

- `chat-model-canary-evaluation`: Reproducible SFW and NSFW model canaries, context-window qualification, workload quality gates, resource isolation, and evidence requirements.

### Modified Capabilities

- `gpu-rebalance`: Permit temporary pre-production reassignment of co-located embedding capacity to isolated chat-model canaries while preserving at least one text-embedding deployment.

## Impact

- Affects `gpu-server` model manifests, canary Compose configuration, benchmark tooling, and operational documentation.
- Temporarily reduces text-embedding replicas from two to one and DINO visual-embedding replicas from two to one during canary evaluation.
- Changes no production model aliases or HeartCode routing until a candidate passes all gates and a separate promotion decision is made.
- Downloads gated Gemma weights and selected 2026 community NSFW/RP GGUF artifacts to Pea's private model storage.
