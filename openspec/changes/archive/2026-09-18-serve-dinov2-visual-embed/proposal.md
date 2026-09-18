## Why

The deployed `heartcode-embed-vision` (nomic CLIP) is great at **text→image** and "same concept" semantics, but CLIP-family embeddings are weak at **fine-grained visual / same-object (instance) similarity** — they map look-alike-but-different things together and don't distinguish a specific object/texture/instance well. **DINOv2** (Meta's self-supervised ViT) is the inverse: image-only, but state-of-the-art at visual/structural similarity — exactly what "find similar objects / more like this image" needs. Serving it adds a complementary **image→image visual-similarity** capability. (Note: DINOv2 is *not* a copy-detection model — that's SSCD/DISC21, a different, non-commercial task for finding edited reuploads of the same image; out of scope here.)

This repo is **serving-only** — it returns vectors; the downstream app stores + searches them (DINOv2 vectors live in their **own** index, separate from the CLIP space).

## What Changes

- **Serve DINOv2 ViT-L/14 (with registers, 1024-d)** behind a new OpenAI-compatible endpoint `heartcode-embed-visual`: given an image, return a fixed-dim visual-similarity vector. **Image-only** (no text branch). **Co-located with the chat (text-generation) servers**, contingent on VRAM fit — fall back to ViT-B/14 if it OOMs (design Decision 2).
- **Rebalance the embed tier to 2 servers of each type** — 2 vision (`heartcode-embed-vision`), 2 text (`heartcode-embed`), 2 DINOv2-visual (`heartcode-embed-visual`) — one co-located per chat GPU 1-6. This drops vision/text from 3→2 each (superseding the `gpu-rebalance` 3+3 layout) to make room for the 2 DINOv2 servers.
- **Add a model server** mirroring `gpu-server/vision-embed/` (PyTorch + `transformers` `AutoModel`, fp32, `/v1/embeddings` image input, CLS-token vector); add it to `docker-compose.yml` (GPU 3 + GPU 6) and `litellm/config.yaml` as `heartcode-embed-visual`.
- **Benchmark** DINOv2 vs nomic-vision on image→image "similar object" probes using `docs/embedding-model-eval.md`.

## Capabilities

### New Capabilities
- `visual-embeddings`: serve image-only DINOv2 embeddings for fine-grained visual / same-object similarity (image→image), over the OpenAI `/v1/embeddings` API, in a vector space separate from the CLIP/text space.

### Modified Capabilities
<!-- None. Complements photo-embeddings (gpu-rebalance); does not modify it. -->

## Impact

- **New GPU service** under `gpu-server/` (DINOv2 via transformers, fp32, eager attention). License: DINOv2 weights are **Apache-2.0** (Meta relicensed — verify), commercial-OK.
- **GPU placement / re-layout** (minimal churn): drop `vision-embed-3` (GPU 3) + `embedding-server-6` (GPU 6); add 2 DINOv2 on those slots (`:8104-8105`). Result: vision 2 (GPU 1-2, `:8101-8102`), text 2 (GPU 4-5, `:8093-8094`), DINOv2 2 (GPU 3+6). GPU 3/6 run ~7.5 GB/8 GB (chat + DINOv2-L) — **monitor; ViT-B fallback**.
- **LiteLLM**: new `heartcode-embed-visual` (2 backends, image-only, `mode: embedding`); `heartcode-embed-vision` and `heartcode-embed` each reduced to 2 backends.
- **Downstream**: a **separate** vector index for DINOv2 vectors (not comparable to `heartcode-embed-vision`).
- **No storage** in this repo.
