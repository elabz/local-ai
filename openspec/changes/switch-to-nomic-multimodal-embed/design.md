## Context

The current embedding tier is 7 `llama-server` containers (ports 8090–8096) co-located on chat GPUs 1–7, each serving `nomic-embed-text-v1.5` (GGUF, 768-d, text-only). LiteLLM exposes them as `heartcode-embed` (`mode: embedding`) with `least-busy` routing.

We are switching to `nomic-ai/nomic-embed-multimodal-3b` — a single-dense-vector multimodal embedder fine-tuned from Qwen2.5-VL-3B-Instruct — to embed **text and images into one shared space**. The hard constraint is the hardware: 8× **P104-100** mining cards (Pascal `sm_61`, 8GB, no Tensor Cores, **no bf16**, crippled fp16 ~1:64, slow PCIe, no NVLink). The Celeron 3865U host has **no AVX**.

Two facts drive the whole design:
1. There is **no GGUF / llama.cpp / vLLM** path for this model — it runs only via PyTorch + `colpali-engine`. So the embedding tier moves off llama.cpp onto a new PyTorch service.
2. A 3B model **cannot** share an 8GB card with an 8B chat model, so the service gets **dedicated GPU(s)** carved out of the chat pool.

## Goals / Non-Goals

**Goals:**
- Serve `nomic-embed-multimodal-3b` behind an OpenAI-compatible `/v1/embeddings` endpoint that accepts **text and image** inputs and returns single dense vectors in a shared space.
- Keep the public `heartcode-embed` model name so text-embedding clients keep working post-cutover.
- Fit the model onto 1–2 dedicated P104-100 GPUs with a precision (fp32 vs fp16) chosen by **on-hardware benchmark**.
- Preserve a clean rollback to the existing text-only embedding tier until the new one is validated.

**Non-Goals:**
- Multi-vector / ColBERT late-interaction retrieval (explicitly rejected `colnomic-*` to avoid rebuilding the retrieval stack).
- Running the 7B variant (needs ~3–4 GPUs in fp32, impractically slow on Pascal).
- High embedding throughput — this tier becomes low-volume/heavier; chat capacity is intentionally traded down by 1–2 GPUs.
- Migrating/translating existing stored vectors — they are re-computed downstream (breaking dimension change is accepted).

## Decisions

### D1 — Model: `nomic-embed-multimodal-3b` (single-vector)
Single dense vector ⇒ drop-in for the existing OpenAI `/embeddings` + LiteLLM pipeline and vector store. Text+image share one space. **Alternatives:** `colnomic-embed-multimodal-3b/7b` (multi-vector — better accuracy but needs a MaxSim/PLAID retrieval rebuild); `nomic-embed-multimodal-7b` (single-vector but ~3 GPUs and slower on Pascal); `nomic-embed-vision-v1.5` (92M, trivial to run but image-only + lower quality, needs a separate text model). The 3B single-vector model is the best capability-vs-hardware balance.

### D2 — Backend: PyTorch + `colpali-engine` (`BiQwen2_5`) behind a FastAPI wrapper
Load with `BiQwen2_5` / `BiQwen2_5_Processor` from `colpali-engine` (pinned). Wrap in a small FastAPI app exposing `/v1/embeddings` and `/health`, mirroring the existing `server.py`/`routes.py`/`metrics.py` pattern so it slots into Prometheus and the watchdog. **Alternatives:** llama.cpp (unsupported), vLLM (unsupported for this model), LocalAI transformers backend (couples embeddings to the image server's `SINGLE_ACTIVE_BACKEND` and gallery flow — more fragile). PyTorch-on-Pascal is already proven on this box by the LocalAI image server (diffusers), which de-risks the no-AVX / `sm_61` concern.

### D3 — GPU allocation: dedicate 1–2 GPUs from the chat pool
The embed service runs on its own GPU UUID(s); those GPUs are removed from the chat services. Final count depends on D4: fp16 (~6–7GB weights) likely fits **1** card; fp32 (~12GB) needs **2** cards via `device_map` sharding (with the known slow-PCIe penalty). Default plan: reassign the lowest-traffic NSFW chat GPU(s). **Alternative:** co-locate on a chat GPU — rejected, 8B+3B won't fit in 8GB.

### D4 — Precision: benchmark fp32 vs fp16 on hardware, then pin
bf16 (the model card default) is unsupported on Pascal, so the wrapper forces `float32` or `float16` at load. fp16 halves VRAM (fits 1 GPU) but Pascal fp16 math is ~1:64 — likely *slower* per request; fp32 is correct and predictable but doubles VRAM (2 GPUs). The service reads precision from an env var; implementation includes a benchmark task that measures VRAM + latency for each and records the chosen default. Until then the design assumes fp32/2-GPU as the safe baseline.

### D5 — Image input transport over the OpenAI `/embeddings` contract
The OpenAI `/v1/embeddings` schema only defines text `input`. We adopt a documented convention: an item in `input` may be a **base64 `data:` image URI** (and/or an `{"image": "<base64|url>"}` object); plain strings are embedded as text. The wrapper detects images, runs the image branch (`model(**processor.process_images(...))`), text via the text branch, and returns vectors in array order. This keeps one `heartcode-embed` model for both modalities. LiteLLM passes `input` through (`mode: embedding`, `drop_params: true`).

### D6 — LiteLLM + ops integration
Replace the 7 `heartcode-embed` deployments with 1–2 pointing at the new service; keep `model_name: heartcode-embed`, `mode: embedding`. Re-tune `model_rate_limits`/parallelism down to match the heavier per-request cost and raise the embedding `request_timeout`. Add the service to `prometheus.yml` scrape targets and the GPU/memory watchdog. Cap image resolution and batch size (no flash-attn ⇒ eager attention activations grow with image tokens).

## Risks / Trade-offs

- **No bf16 + crippled fp16 on Pascal** → fp16 may be slower than fp32 despite less VRAM. → D4 benchmark picks empirically; default fp32.
- **fp32 needs 2 GPUs + slow PCIe sharding (no NVLink/P2P)** → high latency. → Try fp16/1-GPU first in benchmark; document expected latency; set generous timeouts; keep this tier low-volume.
- **High latency vs the old tiny text model** → clients that did bulk text embedding cheaply will slow down. → Re-tune rate limits; communicate the capability/latency trade; consider batching.
- **`colpali-engine` installs from git (`illuin-tech/colpali`)** → unpinned breakage. → Pin a specific commit/tag in the Dockerfile; vendor `qwen-vl-utils`/`transformers`/`accelerate` versions.
- **No-AVX host could crash PyTorch import** → service won't start. → Low risk (LocalAI already runs torch here); validate import as the first build smoke test; if it fails, fall back to a torch build with runtime CPU dispatch / CPU-feature env guards.
- **Vector dimension changes (768 → 3B dim)** → old stored vectors unusable. → **BREAKING**, accepted; downstream re-indexes after cutover; old tier stays up until then.
- **Image-input convention is non-standard** → client confusion. → Document clearly in `CLAUDE.md`/setup docs and the spec; reject malformed inputs with clear errors.
- **flash-attn unavailable** → eager attention activation memory grows with image resolution → OOM on big images. → Cap max image dimension/tokens and batch size.
- **Model license/usage** → must confirm before deploy. → Open question O4; verify on the HF card.

## Migration Plan

1. **Build & fetch** the new embed image; `download-models.sh` pulls `nomic-embed-multimodal-3b` (HF snapshot) into `./models`.
2. **Stand up** the service on a single freed GPU UUID; smoke-test torch import, model load, a text embedding, and an image embedding; verify the vector dimension.
3. **Benchmark** fp32 vs fp16 (VRAM + latency); pin precision and finalize 1- vs 2-GPU layout (D4).
4. **Parallel run**: keep the old `nomic-embed-text` containers up; add the new service to Prometheus + watchdog.
5. **Cutover**: repoint LiteLLM `heartcode-embed` to the new endpoint(s), re-tune rate limits/timeouts; validate end-to-end through the proxy.
6. **Re-index** downstream embeddings against the new model.
7. **Decommission**: remove the 7 `embedding-server-*` services and the old GGUF; update docs (`CLAUDE.md`, port/GPU tables, `docs/`).

**Rollback:** revert `litellm/config.yaml` to the 7 `nomic-embed-text` deployments (still present until step 7) and stop the new service — no data migration needed since old vectors are untouched until re-index.

## Open Questions

- **O1 — Precision & GPU count:** fp16/1-GPU vs fp32/2-GPU — resolved by the D4 benchmark on real hardware.
- **O2 — Embedding dimension:** documented as **3584-d** for both the 3B and 7B variants (vs the old 768-d text model); confirm empirically at model load (task 1.4) and size the vector store for ~4.6× larger vectors.
- **O3 — Image transport:** finalize the exact `input` convention (base64 `data:` URI string vs `{"image": ...}` object vs both) and any size caps.
- **O4 — License:** confirm `nomic-embed-multimodal-3b` license permits our use before deploy.
- **O5 — Batching:** whether to support multi-input batches given eager-attention memory, and the safe max batch/image-token cap.
