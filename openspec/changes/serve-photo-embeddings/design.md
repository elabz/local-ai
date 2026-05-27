## Context

A downstream application wants natural-photo retrieval (text→image and image→image). That requires a **joint-embedding** model that places text and images in one vector space, so the downstream service can compare a text-query vector or an image-query vector against stored image vectors. **This repo only serves the model** — it receives a request and returns embeddings. Vector storage, indexing, ANN/kNN, ranking, and search all live in the downstream application and are **out of scope here**.

Constraints:
- Hardware is the PEA box: P104-100 (8 GB, sm_61 — **no bf16, crippled fp16, no flash-attn**), no-AVX Celeron host (memory `pea-p104-ml-constraints`).
- The in-flight `switch-to-nomic-multimodal-embed` serves `nomic-embed-multimodal-3b` (BiQwen2.5), a **document**-retrieval model (3584-d) — likely a poor fit for natural photos.
- Serving already has a working pattern: `gpu-server/multimodal-embed/` (FastAPI + a loaded model exposing `/v1/embeddings` for text + image).

## Goals / Non-Goals

**Goals:**
- Serve a natural-photo-appropriate joint-embedding model that returns shared-space vectors for both text and images.
- Expose it via the OpenAI `/v1/embeddings` contract behind `heartcode-embed-vision`.
- Run within Pascal limits (fp32, eager attention).

**Non-Goals (downstream / not in this repo):**
- Vector **storage** of any kind — Elasticsearch, pgvector, Qdrant, files.
- **Indexing**, **ingestion**, **kNN/ANN search**, **ranking**, `top_k`/threshold.
- Re-indexing or backfilling corpora.
- Caption generation (no VLM captioning).

## Decisions

### Decision 1: Joint embedding (shared text+image space)
Serve a model that maps text and images into one space, so downstream cosine comparison across modalities is meaningful. **Why:** that is what makes text→image and image→image possible from one stored vector set. **Alternative (caption-then-embed)** rejected: it needs a VLM generation pass and a separate text embedder, is lossy, and heavier on weak GPUs.

### Decision 2: Default to `nomic-embed-vision-v1.5` (768-d)
Serve `nomic-embed-vision-v1.5` (images) paired with `nomic-embed-text-v1.5` (text) — a CLIP-style aligned pair in one **768-d** space. **Why:** tuned for natural-image retrieval; a ViT-B-scale tower runs comfortably in **fp32** on Pascal (avoids crippled fp16 of a 3B model); **Apache-2.0**; the 768-d space matches the `nomic-embed-text-v1.5` we already ran, so downstream text vectors stay comparable. **Usage:** the pair must be used together; text **queries** carry the `search_query:` prefix, images none — the serving layer applies this. **Alternatives:** `jina-clip-v2` (1024-d), SigLIP2 (larger), BiQwen2.5 (document-domain baseline). **Gated by an offline eval (tasks 1.x).**

### Decision 3: OpenAI `/v1/embeddings` contract for text + image
Accept a text string or an image (data URI / base64 / http(s) URL, per the `multimodal-embed` convention) and return OpenAI `data[]` with one vector per input in order. **Why:** consistent with the existing embedding endpoint so LiteLLM and clients are unchanged. Malformed/oversized images → 4xx, never a crash.

### Decision 4: Mirror the `multimodal-embed` serving pattern
Build the server like `gpu-server/multimodal-embed/` (FastAPI, in-process model load, Prometheus metrics, Dockerfile, health-gated readiness). **Why:** proven on this hardware; least new surface.

## Risks / Trade-offs

- **Model underperforms on our photos** → offline eval (cosine recall@k / nDCG) on a representative sample *before* committing the model; keep the model behind config so it can be swapped.
- **Pascal throughput** (crippled fp16) → run the ViT towers in **fp32**; small enough to be fast.
- **Two embedding models** (document BiQwen2.5 + photo vision) competing for limited VRAM/cards → decide coexist vs replace on GPU 7 at deploy time.
- **License** → Apache-2.0 pair avoids the Qwen research-only constraint.

## Migration Plan

1. Build the model server for the chosen model (fp32, eager attn) exposing `/v1/embeddings` for text + image.
2. Add it to `gpu-server/docker-compose.yml` on a GPU; activate the `heartcode-embed-vision` entry in `litellm/config.yaml` (set `api_base`/port).
3. Verify text + image return identical-dimension shared-space vectors through the proxy. **Rollback:** comment the LiteLLM entry / stop the container; nothing else depends on it in this repo.

## Open Questions

- **Model**: does `nomic-embed-vision-v1.5` (768-d) win the offline photo eval, or does a higher-quality alternative (`jina-clip-v2`, SigLIP2) justify its extra cost?
- **GPU placement**: coexist with BiQwen2.5 or replace it on GPU 7 (VRAM/card budget)?
