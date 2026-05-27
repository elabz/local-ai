## Context

We want cross-modal image retrieval: **text→image** (search by description) and **image→image** (search by example). Cross-modal search requires a *joint-embedding* model that places text and images in one vector space; cosine similarity then ranks images against either query type. No "description" text is generated — the model maps the raw query and the image directly into the shared space (the alternative, caption-then-embed via a VLM, was rejected; see Decisions).

Current state and constraints:
- A change already in flight — `switch-to-nomic-multimodal-embed` — deploys `nomic-embed-multimodal-3b` (BiQwen2.5), a **visual-document-retrieval** model (ColPali lineage), 3584-d, on a dedicated Pascal P104-100 (GPU 7).
- Our images are **natural photos**, not documents/screenshots — a probable domain mismatch for BiQwen2.5.
- Hardware is the constrained PEA box: P104-100 (8 GB, sm_61, **no bf16, crippled fp16, no flash-attn**), no-AVX Celeron host. See memory `pea-p104-ml-constraints`.
- We already store **text** embeddings in **Elasticsearch** (`dense_vector` + kNN), so the retrieval substrate exists.
- LiteLLM exposes embeddings behind `heartcode-embed`; image search will call that endpoint, not the GPU server directly.

## Goals / Non-Goals

**Goals:**
- Pick a joint-embedding model that is good at **natural-photo** text→image and image→image retrieval *and* fits Pascal hardware.
- Build a retrieval layer: image **ingestion** (embed→index) and a **query API** (text or image → embed → ANN search → ranked hits).
- **Reuse the existing Elasticsearch** vector store rather than introducing a new database.
- Guarantee a single shared space with consistent L2-normalization and a verified index dimension.

**Non-Goals:**
- Generating human-readable captions for images (no VLM captioning pipeline).
- Multi-vector / late-interaction retrieval (ColNomic/ColPali MaxSim) — out of scope for v1.
- Re-architecting the chat/image GPU servers; only the embedding service and a new search service are touched.
- Building UI; this change exposes an API.

## Decisions

### Decision 1: Joint embedding, not caption-then-embed
Embed the raw text query and images into one space and compare by cosine. **Why:** one model, one index, lowest latency, no lossy caption bottleneck, and it is the standard approach for text→image. **Alternative considered — caption-then-embed** (VLM writes a description per image, embed the caption with a text model, text→text search): gives human-readable descriptions and reuses a text-only embedder, but adds a generation pass per image, compounds errors through the caption, and is heavier on our weak GPUs. Rejected for v1; could be added later for display/filtering.

### Decision 2: Default to `nomic-embed-vision-v1.5` (768-d), a CLIP-family model tuned for natural photos
Adopt **`nomic-embed-vision-v1.5`** paired with **`nomic-embed-text-v1.5`** — a CLIP-style aligned pair sharing a single **768-d** space. **Why this is the default, not just a candidate:**
- **Stay at 768-d.** The vision encoder is trained to land in `nomic-embed-text-v1.5`'s space, so image and text vectors are directly cosine-comparable at 768-d. No dimension change.
- **Reuse existing text vectors.** We already ran `nomic-embed-text-v1.5`, so stored text embeddings (subject to the pooling/normalization check in Risks) stay valid and comparable to new image vectors — we mostly *add* image vectors rather than re-embedding everything. Contrast BiQwen2.5's 3584-d, which is a full breaking re-index.
- **No ES upgrade.** 768-d indexes as a `dense_vector` on *any* Elasticsearch version (cap ≥1024 even on old releases).
- **Pascal-friendly + commercial.** A ViT-B-scale tower runs comfortably in **fp32** on P104-100 (avoids the crippled-fp16 path of a 3B model); **Apache-2.0** lifts the Qwen research-only constraint.

**Usage requirements for correctness:** the pair must be used together (vision-v1.5 for images, text-v1.5 for text); text **queries** must carry the `search_query:` task prefix (images need none) — skipping it measurably hurts retrieval.

**Alternatives considered:** `jina-clip-v2` (1024-d, multilingual, Matryoshka — strong, but not in our existing text space → fuller re-index), SigLIP2 (excellent quality, larger, separate space), and keeping **BiQwen2.5** (document-domain, likely weaker on photos, 3584-d → ES ≥ 8.11 + full re-index, research-only, 3B heavy on Pascal). **The eval (tasks 1.x) decides whether a higher-quality alternative beats the shared-space convenience — do not index at scale before confirming.**

### Decision 3: Reuse Elasticsearch (`dense_vector` + kNN)
Store image vectors in ES as an indexed `dense_vector` with `similarity: cosine`, query with the kNN search API. **Why:** the store already exists for text embeddings; one system to operate; native ANN (HNSW). **Constraint:** indexed `dense_vector` dimension caps at **1024 (ES ≤ 8.x early), 2048, then 4096 (ES ≥ 8.11)**. A 768-d model fits every version; 3584-d (BiQwen2.5) would require ES ≥ 8.11. **Alternative considered:** dedicated vector DB (Qdrant/Milvus) — better at very large scale/filtering, but a new service; deferred unless scale demands it.

### Decision 4: Normalize for cosine; keep text and image vectors in one index
L2-normalize every vector at index and query time so cosine == dot product and scores are comparable across modalities. Store image vectors (and optionally text vectors) in one index/mapping with a shared dimension. **Why:** mixing un-normalized vectors makes cross-modal scores meaningless; a single mapping enforces dimension agreement.

### Decision 5: A thin search service in front of `heartcode-embed`
A new small service (or module) exposes `ingest` and `search` endpoints, calls `heartcode-embed` for embeddings, and talks to ES. **Why:** keeps embedding (GPU box), storage (ES), and orchestration concerns separated; lets us swap the model behind `heartcode-embed` without changing search clients.

## Risks / Trade-offs

- **Model still underperforms on our photos** → run the eval on a representative photo sample with labeled query→image pairs *before* bulk indexing; keep the model behind config so it can be swapped.
- **ES version too old for chosen dimension** → verify version/dims early; prefer the 768-d model which fits any version; if a higher-dim model wins the eval, gate on an ES upgrade or use `halfvec`-equivalent quantized kNN (`int8_hnsw`).
- **Two embedding models diverge** (document model for one use case, photo model here) → the GPU box has limited VRAM/cards; decide whether photo-search supersedes the BiQwen2.5 deployment on GPU 7 or coexists. Coordinate with `switch-to-nomic-multimodal-embed`.
- **Pascal throughput** (crippled fp16) → run CLIP image/text towers in **fp32**; they are small enough to be fast in fp32, unlike the 3B BiQwen.
- **Existing text vectors may not be drop-in compatible** → we ran `nomic-embed-text-v1.5` as a **GGUF in llama.cpp**; the HF/sentence-transformers pairing should share the space, but pooling/normalization can differ. Mitigation: verify on a few samples (embed the same text via both paths, check cosine ≈ 1) before assuming zero text re-index; if they diverge, re-embed text once — still 768-d, still non-breaking dimension-wise.
- **Re-index cost** → at 768-d with the aligned pair this is *additive* (index image vectors), not a breaking full re-embed; only a dimension-changing alternative (e.g. BiQwen2.5 3584-d) forces the breaking path. Store the source-asset reference so re-embedding never needs re-upload.
- **Un-normalized legacy text vectors** already in ES → confirm/normalize existing vectors, or version the index.

## Migration Plan

1. Stand up `nomic-embed-vision-v1.5` (+ `nomic-embed-text-v1.5`) behind `heartcode-embed` (or a sibling name) on the GPU box in fp32; verify both return 768-d and that text+image land in one space.
2. Run the text-compatibility check (Risks); decide reuse-existing-index vs version-a-new 768-d index.
3. Create/confirm the ES index/mapping: 768-d `dense_vector`, `cosine`, HNSW.
4. Backfill: embed and index the existing image corpus (768-d). Re-embed text vectors **only if** the compatibility check fails.
5. Deploy the search service; validate text→image and image→image on the eval set.
6. Cut clients over to the new search endpoint. **Rollback:** keep the old index until validated; the search service points at an index name via config, so reverting is a config flip.

## Open Questions

- **Model**: `nomic-embed-vision-v1.5` (768-d) is the default for its shared-space/no-reindex/no-ES-upgrade advantages; does a higher-quality alternative (`jina-clip-v2` 1024-d, SigLIP2) beat it by enough on the photo eval to justify giving those up?
- **Text-vector compatibility**: do the existing llama.cpp-GGUF `nomic-embed-text-v1.5` vectors line up with the HF vision pairing (cosine ≈ 1 on samples), letting us skip a text re-index?
- **Coexistence**: does photo-search **replace** BiQwen2.5 on GPU 7, or run alongside (VRAM/card budget)?
- **Elasticsearch version** and current `dense_vector` mapping/dims for the existing text index — does it support the chosen dimension, and is the existing index reusable or do we version a new one?
- **Scale**: corpus size (thousands? millions?) — does ES kNN suffice or will we need a dedicated DB / quantization (`int8_hnsw`)?
- **Unify or separate** the text-embedding and image-search models — one space for everything, or a dedicated photo index?
