# DINOv2 Visual Embedding Server

Serves **DINOv2** (ViT-L/14 with registers, 1024-d) image embeddings for
fine-grained **visual / same-object similarity** (image→image), over an
OpenAI-compatible `/v1/embeddings` API. Exposed via LiteLLM as
`heartcode-embed-visual`.

> **Image-only** — DINOv2 has no text encoder; text inputs return **400**.
> **Separate vector space** — these vectors are NOT comparable to
> `heartcode-embed-vision` (CLIP); the downstream app keeps a separate index.
> **Serving only** — stores nothing. Implements openspec `serve-dinov2-visual-embed`.

## Why (vs heartcode-embed-vision / CLIP)

CLIP (nomic-vision) is strong at text→image + "same concept" but weak at
fine-grained visual instance similarity. DINOv2 is the complement: no text, but
SOTA visual/structural similarity — "find visually similar / the same object."
Run both: CLIP for text + coarse semantics, DINOv2 for visual "more like this".

## ⚠️ Best-effort until verified on GPU

`embed_model.py` follows standard DINOv2 usage but hasn't run on a P104-100.
Verify (task 3.2): loads fp32 on cuda, dim == 1024, and **VRAM fits co-located
with chat (~7.5 GB/8 GB)** on GPU 3/6. If it OOMs, set
`MODEL_ID=facebook/dinov2-with-registers-base` (768-d, ~0.4 GB).

## API

`POST /v1/embeddings` — `input` is an image (`data:` URI / base64 / http(s) URL),
or a list of images. Returns OpenAI `data[]`, one L2-normalized vector each.
**Text input → 400.** Malformed/oversized image → 400.
`GET /health` — readiness + dimension. `GET /metrics` — Prometheus.

## Key env vars

| Var | Default | Notes |
|-----|---------|-------|
| `MODEL_ID` | `facebook/dinov2-with-registers-large` | ViT-L/14 (1024-d); `-base` = 768-d fallback |
| `PRECISION` | `float32` | never bf16 on Pascal |
| `MAX_IMAGE_EDGE` | `1024` | longest-edge px cap |
| `MAX_BATCH_SIZE` | `4` | items per forward pass (bounds activation memory) |

Model snapshotted into `/models` by `download-models.sh`. Choosing the variant /
benchmarking vs nomic-vision: see `docs/embedding-model-eval.md`.
