## Why

Our embedding endpoint (`heartcode-embed`) is text-only: 7 llama.cpp containers serving `nomic-embed-text-v1.5` (GGUF). We want multimodal retrieval — embedding **images and text into one shared vector space** so projects can do image↔text and document search. The chosen model, `nomic-embed-multimodal-3b` (single dense vector, Qwen2.5-VL-3B), keeps a standard OpenAI `/v1/embeddings` contract (no late-interaction retrieval rebuild) while adding image understanding, and is the best capability-vs-hardware fit for our 8GB Pascal (P104-100) cards.

## What Changes

- **Add a new GPU embedding service** that serves `nomic-embed-multimodal-3b` via PyTorch + `colpali-engine` (`BiQwen2_5`), exposing an OpenAI-compatible `/v1/embeddings` endpoint that accepts **both text and image inputs** and returns single dense vectors in a shared space.
- **Dedicate 1–2 GPUs** to this service (taken from the chat pool), since the 3B model cannot share an 8GB card with an 8B chat model. Reduces the chat GPU count by 1–2.
- **Retire the 7 llama.cpp text-embed containers** (ports 8090–8096, `nomic-embed-text-v1.5`) and the per-GPU embed co-location pattern.
- **Repoint LiteLLM** `heartcode-embed` to the new service; the API name stays the same so text-embedding clients keep working. Image embedding is exposed through the same model.
- **Precision is decided during implementation** — benchmark fp32 vs fp16 on the actual P104-100 hardware (Pascal has no bf16 and crippled fp16) and pick based on measured VRAM + latency.
- Update `download-models.sh`, GPU/port layout docs, and `CLAUDE.md`.
- **BREAKING**: embedding vector dimension and semantics change (`nomic-embed-text-v1.5` **768-d → 3584-d**, per Nomic docs; confirm on model load). The ~4.6× larger vector also increases vector-store size per record. All existing stored embeddings must be **re-computed/re-indexed**; old and new vectors are not comparable.
- **BREAKING**: embedding throughput/concurrency profile changes — fewer, heavier servers (1–2 GPUs) instead of 7; rate limits must be re-tuned.

## Capabilities

### New Capabilities
- `multimodal-embeddings`: An OpenAI-compatible embedding service that embeds text and images into one shared dense-vector space, backed by `nomic-embed-multimodal-3b`, with defined GPU allocation, precision, VRAM budget, and API contract on Pascal hardware.

### Modified Capabilities
<!-- None: there are no pre-existing OpenSpec specs in openspec/specs/. The text-only embedding behavior was never captured as a spec; it is superseded by the new capability above and described in Impact. -->

## Impact

- **Code / infra**:
  - `gpu-server/docker-compose.yml` — remove 7 `embedding-server-*` services; add one (or two) `multimodal-embed` service(s) on dedicated GPU UUID(s); free the chat GPU(s) reassigned to it.
  - New build artifact for the multimodal embed service (`Dockerfile` + a FastAPI wrapper exposing `/v1/embeddings`, mirroring the existing `server.py`/`routes.py` pattern), with `colpali-engine`, `torch`, `transformers`.
  - `gpu-server/scripts/download-models.sh` — replace the `nomic-embed-text-v1.5` GGUF download with `nomic-ai/nomic-embed-multimodal-3b` (safetensors / HF snapshot).
  - `litellm/config.yaml` — replace the 7 `heartcode-embed` deployments with the new service endpoint(s); re-tune `model_rate_limits`/parallelism; keep `mode: embedding`.
  - `CLAUDE.md`, `docs/pea-server-setup.md`, port/GPU layout tables.
- **APIs**: `heartcode-embed` gains image input; output vector dimension changes (**BREAKING** for stored vectors).
- **Dependencies**: introduces a PyTorch/`colpali-engine` runtime on Pascal (no bf16, no flash-attn, slow fp16) — precision/perf to be validated on hardware.
- **Hardware**: chat capacity drops by 1–2 GPUs; embedding latency expected to rise substantially vs the tiny text model. Rate limits and capacity docs updated accordingly.
- **Downstream**: any consumer storing `heartcode-embed` vectors must re-index after cutover.
