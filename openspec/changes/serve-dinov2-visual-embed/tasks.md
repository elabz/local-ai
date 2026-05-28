## 1. Variant (DECIDED) & checkpoint

- [x] 1.1 Checkpoint: `facebook/dinov2-with-registers-large` (ViT-L/14, 1024-d); `-base` (768-d) = ViT-B fallback. DINOv2 Apache-2.0 (verify checkpoint card on download).
- [ ] 1.2 (Decided: **ViT-L/14 +reg, co-located with chat**; ViT-B fallback if OOM.) Optional: benchmark vs nomic-vision on image→image probes via `docs/embedding-model-eval.md` to confirm the quality win

## 2. Serving implementation

- [x] 2.1 Built `gpu-server/dino-embed/` (`DinoEmbedder`: `AutoModel`, fp32, pooled/CLS → L2-normalized). **Best-effort — verify on GPU (3.2).**
- [x] 2.2 `/v1/embeddings` images → OpenAI `data[]` in order; **text item → 400** (`routes.py`)
- [x] 2.3 Malformed/oversized → 400 (`image_input.py`); `MAX_BATCH_SIZE`/`MAX_IMAGE_EDGE` caps
- [x] 2.4 `/health` (reports dim) + `metrics.py` + `Dockerfile`. All `.py` compile; interface matches routes/server.
- [x] 2.5 `download-models.sh`: snapshots `dinov2-with-registers-large` (+ switched embed downloads to the deployed nomic vision/text)

## 3. Integration (2+2+2 re-layout, minimal churn)

- [x] 3.1 docker-compose: added `dino-embed-1` (GPU 3, `:8104`) + `dino-embed-2` (GPU 6, `:8105`); removed `vision-embed-3` + `embedding-server-6`. 16 services; YAML validated.
- [ ] 3.2 PEA deploy: stop `pea-embed-vision-3` + `pea-embed-6`; start the 2 DINOv2; **verify VRAM ~7.5 GB fits** on GPU 3/6 (else ViT-B); confirm chat still healthy
- [ ] 3.3 LiteLLM: add `heartcode-embed-visual` (2 backends `:8104-8105`, image-only); reduce `heartcode-embed-vision` → 2 (`:8101-8102`) and `heartcode-embed` → 2 (`:8093-8094`); commit + merge; prod pull + restart
- [ ] 3.4 Validate through the proxy: `heartcode-embed-visual` image → vector + dimension; **text input → 4xx**; vision + text still serve

## 4. Docs & validation

- [x] 4.1 `CLAUDE.md` updated (Models table, port/GPU layout, allocation, structure, separate-index note); LiteLLM config also updated (visual added, vision/text→2). _`docs/pea-server-setup.md` deeper refresh = light follow-up._
- [ ] 4.2 Run `openspec validate serve-dinov2-visual-embed --strict`
