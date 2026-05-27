## Why

A downstream search application wants natural-photo retrieval — find images by a similar image (image→image) and by a text description (text→image). That only works if text and images are embedded into **one shared vector space**. This repo's job is to **serve** such an embedding model over the API; it does **not** store, index, or search vectors — that lives in the downstream application. The model currently in flight (`nomic-embed-multimodal-3b` / BiQwen2.5, via [switch-to-nomic-multimodal-embed]) is tuned for **document** retrieval, while the target is **natural photos** — a likely model-domain mismatch to resolve before anyone embeds a corpus.

## What Changes

- **Serve a natural-photo joint-embedding model** behind a new OpenAI-compatible endpoint `heartcode-embed-vision`: given a text string **or** an image, return one embedding vector; text and image vectors share one space so the downstream service can compare them.
- **Default model: `nomic-embed-vision-v1.5` (768-d)** paired with `nomic-embed-text-v1.5` — a CLIP-style aligned pair sharing one space, runnable in **fp32** on Pascal P104-100, **Apache-2.0**. An offline on-photo eval confirms it against `jina-clip-v2` / SigLIP2 (and the BiQwen2.5 baseline) before we commit.
- **Add a model server** (mirroring `gpu-server/multimodal-embed/`) on a GPU, exposing `/v1/embeddings` for text + image inputs, and wire it into `litellm/config.yaml` as `heartcode-embed-vision`.

## Capabilities

### New Capabilities
- `photo-embeddings`: serve shared-space embedding vectors for natural-photo use — accept a text string or an image over the OpenAI `/v1/embeddings` API and return one vector per input in a single text+image space. Serving only; storage/retrieval are out of scope (downstream).

### Modified Capabilities
<!-- None established in openspec/specs/. -->

## Impact

- **Model server / GPU layout**: a new embed service for `nomic-embed-vision-v1.5` (~ViT-B, 768-d, fp32) under `gpu-server/`; GPU assignment decided alongside the BiQwen2.5 deployment (coexist vs replace on GPU 7).
- **LiteLLM**: a `heartcode-embed-vision` model entry (already staged as a commented/PLANNED block in `litellm/config.yaml`; activate on deploy).
- **No storage**: explicitly **no** Elasticsearch / vector DB / index / ingestion / kNN in this repo — the downstream search service owns all of that.
- **License**: `nomic-embed-vision-v1.5` / `nomic-embed-text-v1.5` are Apache-2.0 (vs the Qwen research-only constraint on BiQwen2.5).
