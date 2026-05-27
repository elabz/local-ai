## Why

We want to find images two ways: by uploading a similar image (**image→image**) and by typing a description (**text→image**). The model layer for cross-modal search comes "for free" from a joint-embedding model that maps text and images into one vector space — but we have **no retrieval layer** (no image ingestion, no query API) to use those vectors. Separately, the embedding model currently in flight (`nomic-embed-multimodal-3b` / BiQwen2.5, via [switch-to-nomic-multimodal-embed]) is tuned for **document/screenshot** retrieval, whereas our images are **natural photos** — a likely model-domain mismatch that this change must resolve before indexing anything (re-indexing 3584-d vectors is expensive to redo).

## What Changes

- **Adopt `nomic-embed-vision-v1.5` (768-d) as the default photo model.** It is the image encoder trained to share `nomic-embed-text-v1.5`'s embedding space — the exact text model we already ran — so text↔image comparison works directly at **768-d**. A small on-photo eval confirms it (and tests `jina-clip-v2` / SigLIP2 as higher-quality-but-higher-dim alternatives, with the in-flight BiQwen2.5 as the document-domain baseline). This **supersedes the BiQwen2.5 choice for the photo-search use case**.
- **Add an image-search retrieval layer** on top of the chosen embedding endpoint:
  - **Ingestion**: image → embed → upsert vector + metadata into the vector index.
  - **Query API**: text *or* image query → embed → ANN search → ranked image IDs/metadata, with score threshold and top-k.
  - **Normalization**: L2-normalize vectors at index and query time; compare by cosine.
- **Reuse the existing Elasticsearch vector store** (where text embeddings already live) via `dense_vector` + kNN, rather than standing up a new database. At **768-d** an indexed `dense_vector` fits *any* ES version (the cap is ≥1024 even on old releases) — **no ES upgrade**. (Only a higher-dim alternative would matter: ES ≥ 8.11 → max 4096; BiQwen2.5's 3584-d needs 8.11+.)
- **Re-index (conditional, not inherently breaking)**: image and text vectors must come from the *same* aligned model pair in the *same* space. With `nomic-embed-vision-v1.5` ↔ `nomic-embed-text-v1.5` the dimension stays **768-d** and existing text vectors are **likely reusable** — we mostly *add* image vectors. A model that changes dimension (e.g. BiQwen2.5 → 3584-d) would force a **BREAKING** full re-embed. Coordinated with [switch-to-nomic-multimodal-embed] task 7.1.

## Capabilities

### New Capabilities
- `image-search`: ingest natural-photo images into a vector index and serve cross-modal retrieval — text→image (search by description) and image→image (search by example) — over the shared embedding space, returning ranked, scored results.

### Modified Capabilities
<!-- None yet established in openspec/specs/. The embedding-model behavior lives in the
     in-flight `switch-to-nomic-multimodal-embed` change (not yet archived to specs), so
     model re-selection is captured in this change's design/tasks rather than as a spec delta. -->

## Impact

- **Embedding model / GPU layout**: switch from BiQwen2.5 (3B, 3584-d, GPU 7) to the `nomic-embed-vision-v1.5` (~ViT-B, **768-d**) + `nomic-embed-text-v1.5` pair — much lighter on Pascal P104-100 (no bf16, crippled fp16, no flash-attn) and runnable in fp32. Affects `gpu-server/` (a new or repurposed embed service) and the `heartcode-embed` routing in `litellm/config.yaml`.
- **Elasticsearch**: new image index/mapping with a 768-d `dense_vector` (HNSW, `cosine`); kNN query path. 768-d fits any ES version — no upgrade. Existing 768-d text index likely reusable (verify text vectors came from `nomic-embed-text-v1.5` with matching pooling/normalization).
- **New service**: an image-search API (ingestion + query) — new component, not yet in the repo.
- **Downstream data**: re-indexing of any already-stored image/text vectors on model/dimension change.
- **License**: `nomic-embed-vision-v1.5` / `nomic-embed-text-v1.5` are **Apache-2.0** — this lifts the Qwen research-only (non-commercial) constraint flagged in the in-flight BiQwen2.5 change.
