# Pea LLM Serving Optimization Notes

Last updated: 2026-09-04 (analysis); consolidated 2026-09-18

This is the one optimization note for Pea's llama.cpp chat workers. It
supersedes the older 6 GB / 8K-context recommendations that were written for a
different topology, and it absorbed `OPTIMIZATION-SUMMARY.txt` and
`QUICK-OPTIMIZATION-GUIDE.md` (condensed copies of this file) on 2026-09-18.
Treat every claimed improvement as a benchmark hypothesis until it passes the
repository's canary gates on Pea.

Reliability and incident handling are not covered here. See
[`docs/gpu-inference-availability-runbook.md`](../docs/gpu-inference-availability-runbook.md)
for the watchdog, restart and recovery model and
[`docs/proxy-client-contract.md`](../docs/proxy-client-contract.md) for
concurrency caps, 429/503 semantics and backoff. The February
`RELIABILITY-IMPROVEMENTS.md` (P106 cards, the ASH host, 8 chat GPUs) was removed
as obsolete; git history keeps it.

> **Priority note (2026-09-18):** `serve-aligned-sfw-chat-model` is the
> top-priority open change. The SFW route no longer refuses adult content
> in role, so an SFW candidate's in-role refusal behaviour gates everything
> below, ahead of throughput.

## At a glance

Safe starting configuration for any candidate:

- One slot; full GPU offload.
- Target route context from the start: 16K for SFW, the proposed production
  context for NSFW.
- Batch 128, micro-batch 64, two CPU threads, Q8 K/V cache, `--cache-ram 1024`.
- No multimodal projector for text-only chat.
- No speculative decoding or model-native MTP during initial qualification.
- Pin the llama.cpp image and exact GGUF revision/SHA-256.
- Qualify on GPU 6; keep GPU 5 comfortably below ~7.6 GiB.

Canary queue as of 2026-09-04 (rationale in [Canary shortlist](#canary-shortlist-2026-09-04-refresh)):

| Route | Priority | Candidate | Initial quant |
|---|---:|---|---|
| SFW | 1 | Qwen3.5-9B | Q4_K_M, 6.17 GB |
| SFW | 2 | Ministral-3-8B-Instruct-2512 | Q5_K_M, 6.06 GB |
| SFW | 3 | Meta-Llama-3.1-8B-Instruct | Q5_K_M, 5.73 GB |
| NSFW | baseline | Gemma-4-E4B-Luchador | existing Q5_K_M |
| NSFW | 1 | Gemma-4-E4B-Luchador-Rudo | Q5_K_M, 5.76 GB |
| NSFW | 2 | Nyx-RP-9B-Instruct-2608-v1 | Q4_K_M, 5.78 GB |
| NSFW | 3 | Interferon-gamma RP 9B preview | defer; Q4_K_M |

No-go defaults: no 12B near-full-card model on GPU 5; no Q6/Q8 9B first run; no
speculative/MTP decoding until the base candidate passes all gates; no
promotion based on a model card, load success, or average t/s alone. Do not
assume that a larger batch, micro-batch, cache-reuse value, newer runtime, or
higher-bit quant is faster or safer. Change one variable at a time and retain
the measured rollback configuration.

## Platform and workload constraints

- 8 NVIDIA P104-100 cards, 8 GiB each, Pascal compute capability 6.1.
- Approximately 31 GiB host RAM and a 2-core Celeron without AVX.
- One model replica per chat GPU; speech and image workloads reserve their own
  cards, while embedding services share selected cards.
- Production chat workers use llama.cpp build b8027. The isolated canary image
  currently uses b10566 (`bb4caa754`). Keep the build and model artifact pinned
  by immutable revision and digest.
- SFW admission requires a 16K context window and the real `site-2017`
  workload. The current cold decode floor is 12 tokens/s.
- NSFW admission requires at least 12 tokens/s at the proposed context plus
  allowed-adult, prohibited-content, instruction, repetition, and blind prose
  gates.
- GPU 5 has produced corrupt or empty generations when a process holds more
  than roughly 7.6 GiB. Keep it well below that region; validate on GPU 6 first
  and do not infer that a successful load means healthy generation.

The latest completed comparison is
[`final-comparison-2026-09-04.md`](../openspec/changes/archive/2026-09-18-evaluate-modern-chat-model-canaries/evidence/final-comparison-2026-09-04.md).

## Current baseline

The production compose file defaults chat workers to 16K context, batch 128,
micro-batch 64, two CPU threads, one slot, Q8 KV cache, cache reuse 256 and
`--cache-ram 1024` (verified in `pea-gpu-1`, llama.cpp b8027, on 2026-09-18).
These are sensible conservative defaults for the host, but none should be
called optimal without an A/B run.

Important corrections to the previous notes:

- `--cache-reuse 256` is a reuse threshold/chunk-size control, not 256
  conversation slots. Slot count is controlled by `--parallel`.
- Embedding-only inference does not benefit from an autoregressive KV cache in
  the same way chat generation does. Do not add chat KV-cache flags to all
  embedding workers expecting large savings.
- Matching `ubatch` to `batch` is not automatically faster. On this CPU and
  Pascal hardware it can increase activation memory or hurt latency; measure
  128/64 against alternatives.
- Q6 is not a universal sweet spot. On an 8 GiB card, model family, tokenizer,
  context, KV layout, runtime workspace, and co-located services matter more
  than the GGUF file size alone.
- Flash attention support and benefit are backend/model/build-specific. Verify
  the startup log and output correctness rather than assuming it is active.

## Recommended serving strategy

### 1. Preserve one-slot, full-offload workers

Use one slot per 8 GiB card and offload all layers when the complete runtime
allocation fits with operational margin. Extra parallel slots multiply KV
cache and activation pressure and are a poor trade on this fleet. Scale with
replicas and LiteLLM routing rather than multiple sequences on one card.

Avoid splitting an 8–12B dense model across two P104s as a default: it consumes
two scarce cards and adds inter-GPU/PCIe coordination. Use a second card only
for a deliberate experiment that measures end-to-end latency.

### 2. Select quantization from measured allocation

Starting points, not promotion rules:

- 7–8B conventional models: Q5_K_M when the file is around 5.7–6.1 GB;
  otherwise Q4_K_M.
- 9B or hybrid models: Q4_K_M first. Move to Q5 only if 16K allocation retains
  at least several hundred MiB of healthy headroom and decode still clears the
  floor.
- 12B models: Q4_K_M only, GPU-6-only during qualification. The latest Gemma
  3 12B occupied about 7,949 MiB at 16K and is unsuitable for GPU 5.

Always record GGUF revision, SHA-256, actual VRAM after load, peak VRAM during
long prefill, host RSS, and output integrity. File size alone is insufficient.

### 3. Keep Q8 KV as the default; test Q4 KV only as a rescue path

Q8 K/V is the current quality-conscious baseline. If a promising candidate
misses the 16K memory gate narrowly, compare Q4 KV against Q8 KV using the full
schema, safety, long-context, and prose suites. Do not trade output stability
for context capacity silently.

### 4. Tune batch and micro-batch empirically

For each admitted model, compare at least:

| Matrix | Batch | Micro-batch | Purpose |
|---|---:|---:|---|
| Baseline | 128 | 64 | Known conservative configuration |
| A | 128 | 128 | Test larger physical batches |
| B | 256 | 64 | Test fewer logical prefill chunks |
| C | 256 | 128 | Test combined change if memory allows |

Measure cold and warm TTFT, prompt tokens/s, decode p10/median, peak VRAM,
host RSS, and correctness on identical requests. The 2-core CPU means a larger
batch can help or hurt; there is no safe percentage improvement to assume.

### 5. Exploit stable-prefix reuse, but verify hits

The repeated HeartCode system prompt and character-card prefix are the best
cache opportunity. Keep the prompt ordering and serialization byte-stable and
inspect llama.cpp logs/metrics to prove reuse. Benchmark cold and warm paths
separately. Gemma 3 sliding-window cache disabled cache reuse in the completed
campaign, so treat reuse as model-dependent.

### 6. Keep host-memory pressure bounded

The b10566 canary workers reached their 8 GiB cgroup limits and used far more
anonymous host memory than b8027 production workers. Before promoting a newer
runtime, run concurrent chat and embedding load, watch swap in/out, OOM events,
container restarts, and request latency, and retain the old image for rollback.
Do not use `--mlock` as a substitute for memory budgeting.

Keep `CACHE_RAM` (llama-server `--cache-ram`) set. llama.cpp's implicit 8192 MiB
host prompt cache let six workers OOM the host on 2026-09-18; every compose
service's `mem_limit` must also fit the host budget that
`scripts/check-memory-budget.py` enforces in CI.

### 7. Separate runtime qualification from model qualification

New architectures may require newer llama.cpp builds. First prove that the
runtime loads the exact GGUF and returns coherent direct responses on Pascal;
then run model-quality gates. A model should not cause an unreviewed production
runtime upgrade.

Do not enable speculative decoding or model-native MTP by default. It adds
runtime/version complexity and memory use; evaluate it only after a candidate
already passes without it and only if decode, rather than prefill or CPU work,
is the measured bottleneck.

## Canary shortlist: 2026-09-04 refresh

### SFW, in test order

1. **Qwen3.5-9B, Q4_K_M (6.17 GB)** — strongest new capability candidate.
   Official results report IFEval 91.5 and strong long-context/agent scores.
   Start on GPU 6 at 16K without the vision projector. Qwen3.5 thinks by
   default, so direct-response mode, streaming, reasoning-marker leakage,
   native JSON schema, and multi-turn tools are pre-admission gates.
2. **Ministral-3-8B-Instruct-2512, Q5_K_M (6.06 GB)** — lower-risk
   direct-response alternative with documented system-prompt, function-call,
   and JSON support. Test Q4_K_M (5.42 GB) if Q5 lacks allocation margin. Its
   multi-turn tool-call ID/template round trip must pass on the pinned build.
3. **Meta-Llama-3.1-8B-Instruct, Q5_K_M (5.73 GB)** — older but valuable
   control with a mature llama.cpp path and documented tool formats. It is a
   canary only if its real in-role SFW refusal and `site-2017` precision beat
   the current failures; age alone does not disqualify a stable control.

Do not advance another 12B SFW model until the precision gate/prompt contract
is reviewed. Gemma 3 12B achieved perfect validity and high-risk recall but
only 57.9% actionable precision and missed the separate cold throughput floor.

### NSFW, in test order

Keep **Gemma-4-E4B-Luchador Q5_K_M** as the measured baseline: it remains the
only 2026 challenger to pass all machine and safety gates, although human blind
prose scoring and the product decision on multi-turn tools remain open.

1. **Gemma-4-E4B-Luchador-Rudo, Q5_K_M (5.76 GB)** — best first challenger.
   It shares Luchador's architecture and intended thinking-off template while
   deliberately increasing character/style signal. Run the same prohibited
   suite and a three-arm blind packet; stronger prose must not weaken safety.
2. **Nyx-RP-9B-Instruct-2608-v1, Q4_K_M (5.78 GB)** — best architecture-diverse
   challenger. It is a Qwen3.5 9B RP fine-tune and is explicitly described as
   the finished v1. Q5_K_M (6.64 GB) is too aggressive for the first Pea run.
   It inherits the Qwen3.5 direct-response/runtime risks, and its private
   training data requires provenance review before promotion.
3. **Interferon-gamma RP 9B preview, Q4_K_M (5.78 GB)** — deferred exploratory
   arm only. Its card calls it unstable, and the Nyx author says the testing
   variants generally underperformed v1. Test only if Nyx v1 passes mechanics
   but exposes a specific prose weakness worth exploring.

Screened out for this wave: 12B RP models (memory/thermal risk), Q6/Q8 9B
quants (insufficient headroom), and merges whose own cards warn of reduced
instruction following or amplified hallucination.

## Admission sequence

1. Pin repository revision, GGUF filename, size, and SHA-256.
2. Load on GPU 6 with one slot, baseline batch settings, target context, Q8 KV,
   and no vision projector.
3. Record idle and peak VRAM, host RSS, temperature and startup warnings, and
   run repeated coherence probes; never rely on load success alone.
4. Verify direct response, streaming, retrieval, JSON/schema, tool calls, and
   multi-turn tool-result continuation as applicable.
5. Run cold/warm performance matrices and reject below the route floor.
6. Run the frozen SFW or NSFW quality/safety suite under the production system
   prompt and sampler.
7. For NSFW finalists, run provider-blind prose review against Luchador and
   Lumimaid.
8. Run concurrent host/GPU soak monitoring, restore displaced services, and
   confirm no public alias changed unless promotion is explicitly approved.

## Research references

- Qwen3.5-9B model card: https://huggingface.co/Qwen/Qwen3.5-9B
- Qwen3.5-9B GGUF sizes: https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF
- Ministral-3-8B official card: https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-BF16
- Ministral-3-8B GGUF sizes: https://huggingface.co/unsloth/Ministral-3-8B-Instruct-2512-GGUF
- Llama 3.1 8B Instruct: https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct
- Llama 3.1 GGUF sizes: https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF
- Luchador Rudo: https://huggingface.co/rpDungeon/Gemma-4-E4B-Luchador-Rudo
- Luchador Rudo GGUF sizes: https://huggingface.co/mradermacher/Gemma-4-E4B-Luchador-Rudo-GGUF
- Nyx v1: https://huggingface.co/Indexnusrefather/Nyx-RP-9B-Instruct-2608-v1
- Nyx v1 GGUF sizes: https://huggingface.co/mradermacher/Nyx-RP-9B-Instruct-2608-v1-GGUF
