# Multimodal Embedding Server

OpenAI-compatible `/v1/embeddings` service backed by
[`nomic-ai/nomic-embed-multimodal-3b`](https://huggingface.co/nomic-ai/nomic-embed-multimodal-3b)
(a PEFT/LoRA adapter on `Qwen/Qwen2.5-VL-3B-Instruct`), served via PyTorch +
`colpali-engine` (`BiQwen2_5`). It embeds **text and images into one shared
dense-vector space** (3584-d) on Pascal P104-100 GPUs. Replaces the 7 llama.cpp
`nomic-embed-text-v1.5` containers behind the `heartcode-embed` model name.

> **License:** the model inherits the **Qwen RESEARCH LICENSE** (non-commercial /
> research & evaluation only). Commercial use requires a separate Alibaba Cloud
> license. See the openspec change `switch-to-nomic-multimodal-embed` (O4).

## Hardware constraints (Pascal `sm_61`, no-AVX host)

- **No bf16** — precision is forced to `float32` or `float16` (`PRECISION` env).
- **Crippled fp16** (~1:64) — fp16 fits 1 card but may be slower per request.
- **No flash-attn** — attention is `eager` (`ATTN_IMPLEMENTATION=eager`).
- fp32 (~15GB) needs **2 GPUs** (`device_map=auto`, no CPU offload); fp16
  (~7.5GB) targets **1 GPU**. Final precision/GPU-count chosen by benchmark.

## Image input convention

The OpenAI `/v1/embeddings` schema only defines text `input`. This service
extends it (no other endpoint changes):

| `input` item                         | Treated as |
|--------------------------------------|------------|
| plain string                         | **text**   |
| `data:image/...;base64,<...>` string | **image**  |
| `{"image": "<data-uri \| base64 \| http(s) url>"}` | **image** |
| `{"text": "<string>"}`               | **text**   |

`input` may be a single item or an array; vectors are returned in input order
(OpenAI `data[]` shape). Items declared as images that cannot be decoded return
**HTTP 400** naming the offending index — the service does not crash. Images are
downscaled to `MAX_IMAGE_EDGE` px and requests are capped at `MAX_INPUT_ITEMS`.

### Examples

```bash
# text
curl -s localhost:8100/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"heartcode-embed","input":"a red bicycle"}'

# image (base64 data URI)
curl -s localhost:8100/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"heartcode-embed","input":{"image":"data:image/png;base64,iVBOR..."}}'

# mixed batch (order preserved)
curl -s localhost:8100/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"heartcode-embed","input":["a red bicycle",{"image":"https://.../bike.jpg"}]}'
```

## Key env vars

| Var | Default | Notes |
|-----|---------|-------|
| `PRECISION` | `float32` | `float32` or `float16` (never bf16) |
| `DEVICE_MAP` | _(auto)_ | empty → `cuda:0` (1 GPU) / `auto` (>1 GPU) |
| `ATTN_IMPLEMENTATION` | `eager` | no flash-attn on Pascal |
| `MAX_IMAGE_EDGE` | `1024` | longest-edge px cap (bounds image tokens) |
| `MAX_BATCH_SIZE` | `4` | items per forward pass |
| `MAX_INPUT_ITEMS` | `64` | reject oversized request arrays |
| `METRICS_PORT` | `9091` | Prometheus (same format as GPU servers) |

## Smoke test / benchmark

`bench.py` embeds text + a generated image, prints the embedding dimension and
per-request latency, and reports peak VRAM (`nvidia-smi`). Used for the openspec
benchmark tasks (precision/VRAM/latency):

```bash
python3 bench.py --base http://localhost:8100 --runs 5
```
