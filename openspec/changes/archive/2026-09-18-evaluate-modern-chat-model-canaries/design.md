## Context

Pea has eight 8 GiB P104-100 GPUs and 31 GiB host RAM. SFW chat occupies GPUs 1-3; NSFW chat occupies GPUs 4-6, with text embeddings co-located on GPUs 4-5 and DINO visual embeddings on GPUs 3 and 6. GPU 5 currently runs an isolated Qwen3 canary instead of its normal NSFW replica. Current production chat uses llama.cpp build 8027 while the canary image uses build 10566.

The real-world SFW workload is the frozen `site-2017` tool-demand extraction benchmark. Its prompts reach approximately 14K tokens and expose long-context schema-following failures that short synthetic prompts do not. Pea is not yet in production, so temporary loss of one replica is acceptable, but public aliases and the surviving controls must remain stable.

## Goals / Non-Goals

**Goals:**

- Reproducibly evaluate Gemma 3 and the approved 2026 Gemma 4 NSFW/RP shortlist on the actual Pea hardware.
- Treat usable context length, prompt ingestion, decode throughput, quality, and stability as joint selection gates.
- Keep one current NSFW deployment as an online control and at least one deployment for each temporarily reduced embedding model.
- Produce enough evidence to select or reject candidates and safely run the outstanding SFW mop-up if a winner qualifies.

**Non-Goals:**

- Changing production model aliases or promoting a winner automatically.
- Permanently redesigning embedding placement.
- Testing vision input for Gemma; this campaign evaluates text chat only.
- Claiming the model's advertised maximum context is usable on Pea without measurement.

## Decisions

### Use fixed physical slots and direct canary ports

GPU 5 will host the Gemma canary after stopping its current Qwen canary and `pea-embed-5`. GPU 6 will host the NSFW challenger after stopping `pea-gpu-6` and `pea-embed-dino-2`. GPU 4 remains the Lumimaid control and retains `pea-embed-4`. Canaries use direct, non-public ports and are not added to production aliases.

This layout permits simultaneous NSFW A/B tests and dedicates nearly all 8 GiB on GPU 5 to Gemma 3 12B. Using GPU 4 for the challenger was rejected because it would remove the intended simultaneous control.

### Pin the llama.cpp canary build

Canaries will use the already validated Pascal-compatible build lineage at commit `bb4caa754` (build 10566), or a newer explicitly pinned commit if required by a candidate and verified on compute capability 6.1. The unpinned Dockerfile build is unsuitable for reproducible evaluation.

Ministral compatibility requires an actual model-load, health, generation, Jinja template, JSON-schema, and multi-turn tool-call probe. Known tool-call ID/template incompatibility is a rejection for tool-oriented SFW use unless worked around without weakening validation.

### Prefer Gemma 3 12B Q4_K_M with a high-fidelity fallback

The first SFW candidate is the official `ggml-org/gemma-3-12b-it-GGUF` Q4_K_M artifact. If it cannot load safely or pass 16K context and throughput gates, the fallback is Gemma 3 4B Instruct Q8_0. The multimodal projector is not downloaded because image input is out of scope.

### Evaluate the 2026 Gemma 4 NSFW/RP shortlist in direct-response mode

The original Huihui Qwen3 8B challenger established that a modern 8B model can exceed the mechanical throughput floor, but its reasoning phase is not the desired production interaction. It remains historical evidence and is replaced for selection by three 2026 Gemma 4 candidates:

1. `rpDungeon/Gemma-4-E4B-Luchador`, Bartowski Q5_K_M GGUF, as the RP/creative-writing specialist. Its model card reports a thinking-off instruction-following evaluation and a documented multi-turn RP training mix.
2. `HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced`, native Q4_K_M QAT GGUF, as the larger-capacity challenger. Its 6.9 GiB-class artifact is admitted only to progressive memory/context qualification on the 8 GiB card.
3. `HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive`, Q6_K_P GGUF, as the refusal-free control with comfortable KV-cache headroom.

All three use their embedded Gemma 4 Jinja template, omit multimodal projectors, and run with native reasoning disabled. The canary configuration exposes one candidate at a time on the same isolated GPU 6 port; distinct LiteLLM IDs identify the expected loaded artifact but do not create public routing. Luchador and both HauhauCS artifacts remain subject to exact revision, digest, Gemma-license, provenance, prohibited-content, and private allowed-adult refusal gates.

### Qualify context progressively

Each SFW candidate is launched and tested at 4K, 8K, 16K, 24K, and 32K, stopping after a hard failure or unsafe memory margin. Sixteen thousand tokens is mandatory because the real workload reaches roughly 14K. Twenty-four and 32K are preferred headroom, not promotion gates.

At each size, measure model load, steady-state VRAM, host RAM/swap, prompt processing, time to first token, decode p10/median/mean, output validity, positional retrieval, and restarts. Context claims are recorded as advertised and independently as Pea-qualified.

### Separate microbenchmarks, frozen quality evaluation, and mop-up

Synthetic prompts measure mechanics and positional retrieval. The frozen `site-2017` manifest measures schema validity, actionable precision, high-risk recall, evidence invention, and workload latency. Failed production calls are excluded from blind selection and are retried only after a winner passes the frozen evaluation.

Provider-side `json_schema` is preferred but is not itself a model-selection gate. When llama.cpp grammar enforcement is incompatible with a candidate's control tokens, the evaluator may use prompt-constrained JSON mode: include the complete output contract in the prompt, omit `response_format`, perform syntax-only extraction of a returned object, validate the unchanged schema, and apply bounded ordinary retries. This mode may remove markdown fences or surrounding prose but may not add fields, coerce semantic values, or fabricate missing output. The report records native-schema validity, cleanup-assisted validity, and irrecoverable schema failure separately.

### Use conservative throughput gates

SFW requires p10 decode throughput of at least 10 tokens/second at 16K. NSFW requires p10 of at least 12 tokens/second at the selected production context. Means alone cannot qualify a model. A restart, OOM, GPU fallback, sustained swap thrashing, identifier leak, invented evidence, or failed safety recall gate disqualifies the tested configuration.

## Risks / Trade-offs

- [Gemma 3 12B Q4_K_M leaves little VRAM for KV cache] → Stop the co-located embedding replica, start at 4K, use measured KV-cache quantization only if quality remains acceptable, and fall back to 4B Q8_0.
- [Long prompt prefill can be slow even when decode passes] → Record prompt throughput and end-to-end latency separately and enforce workload-level review.
- [Stopping replicas reduces redundancy] → Keep one text-embedding and one DINO deployment healthy, operate only pre-production, and provide exact rollback commands.
- [Community NSFW models have weak provenance] → Record source revision, license, base model, quantizer, digest, and reject artifacts with unclear redistribution or model lineage.
- [Gemma 4 support or direct-response controls differ across llama.cpp builds] → Use the pinned canary image first, verify the embedded template and `--reasoning off`, and move to a newer explicit pin only if the current build cannot load the model.
- [Gemma 4 12B Q4_K_M leaves little VRAM for KV cache] → Start at 4K with one slot and quantized KV, stop on unsafe margin, and do not infer fit from desktop CPU-offload reports.
- [Benchmark overfitting] → Keep frozen quality examples blind, use separate mechanical prompts, and do not use mop-up retries for candidate selection.
- [New llama.cpp behavior differs from production] → Pin the commit, retain production containers as controls, and test API/template compatibility explicitly.
- [Prompt-constrained JSON is less deterministic than grammar enforcement] → Keep the 98% valid-output gate, unchanged semantic validation, bounded retries, and separate raw/cleanup validity metrics; never repair missing or invalid semantic fields.

## Migration Plan

1. Record baseline container health, restart counters, memory, and current throughput.
2. Build or verify the pinned Pascal canary image locally and on Pea.
3. Download candidates into private model storage and verify exact digests.
4. Stop only the displaced replica, launch the corresponding direct-port canary, and verify health before load testing.
5. Run progressive context and quality matrices, preserving safe aggregate evidence.
6. Restore displaced services immediately after testing or on any unsafe condition.
7. Make no alias or permanent topology change until a separate promotion decision.

Rollback consists of removing the canary container and restarting the exact displaced Compose service; no model manifest or LiteLLM routing rollback is needed because public routing is unchanged.

## Open Questions

- Which of the three admitted 2026 Gemma 4 candidates passes Pea's mechanical, allowed-adult refusal, prose, and prohibited-content gates?
- Whether Gemma 3 12B requires Q8 KV cache, Q4 KV cache, or a reduced batch size to qualify at 16K on this Pascal GPU.
- Whether the winning SFW model justifies a permanent embedding relocation or only a reduced replica count.
