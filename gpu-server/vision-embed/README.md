# Vision Embedding Server

Serves the **natural-photo** embedding pair — `nomic-embed-vision-v1.5` (images)
+ `nomic-embed-text-v1.5` (text) — in one shared **768-d** space over an
OpenAI-compatible `/v1/embeddings` API. Text and image vectors are directly
comparable (cosine), enabling downstream **text→image** and **image→image**
search. Exposed via LiteLLM as `heartcode-embed-vision`.

> Implements openspec change `serve-photo-embeddings` tasks 2.1–2.4. **Serving
> only** — this service stores nothing; indexing/retrieval live downstream.

## ⚠️ Best-effort — verify on GPU

`embed_model.py` follows Nomic's documented usage but has **not** been run on a
P104-100. Before relying on it, smoke-test on hardware (openspec task 3.3):
`torch.cuda` available, both towers load in fp32, text dim == image dim == 768,
and a matching text/image pair scores high cosine. The model is config-driven,
so the eval (tasks 1.x) may swap it.

## Why this model (vs the BiQwen2.5 multimodal-embed service)

`multimodal-embed/` serves `nomic-embed-multimodal-3b` (BiQwen2.5), tuned for
**document** retrieval (3584-d, 3B, heavy on Pascal). This service targets
**natural photos** with a CLIP-style pair: ~ViT-B + BERT towers, **768-d**,
runs in **fp32** on Pascal, **Apache-2.0**.

## API

`POST /v1/embeddings` — `input` is a string, a `data:` image URI / `{"image": ...}`
object, or a list mixing them. Returns OpenAI `data[]` with one vector per input
in order. Malformed/oversized images → 400. Text is embedded as a **query**
(`search_query:` prefix); images get none.

`GET /health` — 503 until both towers load; reports the shared dimension.
`GET /metrics` — Prometheus (shared metric names with the GPU servers).

## Key env vars

| Var | Default | Notes |
|-----|---------|-------|
| `VISION_MODEL_ID` | `nomic-ai/nomic-embed-vision-v1.5` | image tower |
| `TEXT_MODEL_ID` | `nomic-ai/nomic-embed-text-v1.5` | text tower (aligned space) |
| `PRECISION` | `float32` | `float32` or `float16` (never bf16) |
| `TEXT_QUERY_PREFIX` | `search_query: ` | nomic text-query prefix; `""` to disable |
| `MAX_IMAGE_EDGE` | `1024` | longest-edge px cap |
| `MAX_BATCH_SIZE` | `8` | items per forward pass |

Both models are `trust_remote_code`; `download-models.sh` should snapshot them
into `/models` for offline first load (integration task 3.1).
