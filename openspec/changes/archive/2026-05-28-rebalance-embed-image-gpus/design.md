## Context

8× P104-100 (8 GB). Current: GPU 1-3 SFW chat + text-embed, GPU 4-6 NSFW chat + text-embed, GPU 7 dedicated vision-embed (~1.1 GB used of 8), GPU 8 image. Text-embed already co-locates with chat (proven, ~0.35 GB). vision-embed is ~1.1 GB (verified), so it can co-locate too — freeing GPU 7. 1-indexed GPU N maps to specific UUIDs (see compose header); "GPU 7" = `GPU-f417c539`, "GPU 8" = `GPU-c710b68a`.

## Goals / Non-Goals

**Goals:** co-locate 3 text + 3 vision embed on the chat GPUs; free GPU 7 for a 2nd image server; load-balance image gen; keep all LiteLLM model names + chat/embed behavior.

**Non-Goals:** changing chat capacity; storage/search (downstream); reviving BiQwen2.5.

## Decisions

### Decision 1: Embed placement — vision on SFW (1-3), text on NSFW (4-6)
Per the chosen split. Vision-embed (~1.1 GB) co-locates with the 3 SFW chat GPUs; the existing 3 text-embed on NSFW GPU 4-6 stay (`:8093-8095`). Removes the 3 text-embed on GPU 1-3 and the dedicated GPU-7 vision.

### Decision 2: 2nd image server shares LocalAI volumes
The new image server on `GPU-f417c539` mounts the same `image_backends` + `models` volumes as the GPU-8 server, so the cuda12-diffusers backend and SSD-1B model are already present — fast start, no ~7.4 GB re-download. Port `:5101`.

### Decision 3: LiteLLM load-balances per model name
`heartcode-embed-vision` → 3 (`:8101-8103`), `heartcode-embed` → 3 (`:8093-8095`), `heartcode-image` → 2 (`:5100`,`:5101`). `least-busy` strategy spreads load.

## Risks / Trade-offs

- **VRAM tight on GPU 1-3** (chat ~6.2 GB + vision ~1.1 GB ≈ 7.3 GB) → under full chat KV (N_CTX=16384) + a vision image batch it could approach 8 GB. Mitigate: keep vision `MAX_BATCH_SIZE` modest; monitor; fall back to a dedicated card if OOM appears.
- **Two LocalAI instances sharing `image_backends`** → backend already installed (server #1 running), so #2 skips install; concurrent install only a risk if both first-start together (they won't).
- **Live disruption** → stopping text-embed on GPU 1-3 briefly drops `heartcode-embed` capacity to the 3 NSFW backends; chat unaffected.

## Migration Plan

1. Compose: add 3 `vision-embed-{1,2,3}` (GPU 1-3, `:8101-8103`); remove the dedicated vision + text-embed 1-3; add `image-server-2` (GPU 7, `:5101`).
2. PEA: stop `pea-embed-1/2/3` + `pea-embed-vision-1`; `up -d` the 3 co-located vision + image-server-2; validate health + dims + an image gen.
3. LiteLLM: 3+3 embed, 2 image; commit → prod `git pull` + restart → validate.
**Rollback:** restore prior compose + config from git; restart.

## Open Questions

- Does GPU 1-3 hold up under peak chat + vision load, or does vision need to move back to a dedicated card?
