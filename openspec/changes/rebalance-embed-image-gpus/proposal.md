## Why

vision-embed runs on a dedicated GPU 7 using only ~1.1 GB of 8 GB — wasteful. Text-embed is already co-located with chat; vision-embed can be too. Co-locating the embeds frees GPU 7, which we use for a **2nd image-generation server** to load-balance image gen (currently a single GPU-8 server). Net: same chat/embed capability, better GPU utilization, 2× image throughput.

## What Changes

- **Co-locate embeddings on chat GPUs** (3 text + 3 vision), replacing the dedicated GPU-7 vision server:
  - GPU 1-3 (SFW chat): add 3 co-located **vision-embed** instances → `heartcode-embed-vision` (`:8101-8103`); remove the 3 text-embed there.
  - GPU 4-6 (NSFW chat): keep the existing 3 **text-embed** → `heartcode-embed` (`:8093-8095`).
- **Free GPU 7** (`GPU-f417c539`): remove the dedicated `vision-embed`; deploy a **2nd image server** there → `heartcode-image` load-balanced across GPU 7 + GPU 8 (`:5101` + `:5100`), sharing the LocalAI backend + model volumes (no re-download).
- **LiteLLM**: `heartcode-embed-vision` → 3 backends, `heartcode-embed` → 3 backends, `heartcode-image` → 2 backends.

## Capabilities

### New Capabilities
- `gpu-rebalance`: embeddings co-located on chat GPUs (3 text + 3 vision) and image generation load-balanced across 2 GPUs, with all LiteLLM model names unchanged and each routed backend live.

### Modified Capabilities
<!-- None established in openspec/specs/. -->

## Impact

- **VRAM**: GPU 1-3 go from chat+text-embed (~6.5 GB) to chat+vision-embed (~7.3 GB) — tighter on 8 GB; bound vision batch size + monitor.
- **Live services**: stop text-embed on GPU 1-3 + the dedicated vision; start 3 co-located vision + 1 new image server. Chat keeps running throughout.
- **LiteLLM (prod 192.168.0.152)**: config update + restart (brief blip).
- **Image server #2**: shares `image_backends`/`models` volumes so the cuda12-diffusers backend + SSD-1B are not re-downloaded.
