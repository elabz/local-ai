## 1. Prod LiteLLM cutover (ssh elm / 192.168.0.152)

- [x] 1.1 Reconcile `heartcode-embed` (merged config pointed it at the shelved `:8100`): **restore-legacy** → 4 text-embed backends (`:8090-8093`, per "4 text-embed servers"). Also removed the dead `heartcode-chat-nsfw` `:8086` deployment (pea-gpu-7 was removed) and fixed the NSFW header (3 GPUs); updated `CLAUDE.md`. All routed `api_base`s now map to live backends.
- [ ] 1.2 `ssh elm`: `git pull origin main` (config is repo-mounted at `./config.yaml`)
- [ ] 1.3 Restart LiteLLM (`docker compose up -d litellm`) to reload the config
- [ ] 1.4 Validate through the proxy: `heartcode-embed-vision` text + image → 768-d, AND `heartcode-embed` still returns vectors (no dead route)
- [ ] 1.5 Confirm rollback path: revert config + restart restores prior routing

## 2. Offline model eval (completes serve-photo-embeddings 1.x)

- [ ] 2.1 Assemble a representative natural-photo sample with text→image and image→image probes
- [ ] 2.2 Embed candidates (`nomic-embed-vision-v1.5`, `jina-clip-v2` / SigLIP2; BiQwen2.5 baseline); score cosine recall@k / nDCG; record VRAM + latency in fp32
- [ ] 2.3 Confirm `nomic-embed-vision-v1.5` as default or swap; record the decision in `CLAUDE.md` and `serve-photo-embeddings` design

## 3. Cleanup

- [x] 3.1 Prune the unused `local-ai-embed-mm` image + cached `Qwen2.5-VL-3B` base on PEA — removed `local-ai-embed-mm:latest` + `models--Qwen--Qwen2.5-VL-3B-Instruct` + `models--nomic-ai--nomic-embed-multimodal-3b` (root-owned, removed via root container); **~19 GB reclaimed** (57→75 GB free). Kept `multimodal-embed/` source + `nomic-bert-2048` (text-tower code). vision-embed still healthy.
- [ ] 3.2 Update `docs/pea-server-setup.md` (vision-embed bring-up, GPU/port layout, `heartcode-embed-vision`)
- [x] 3.3 Delete the merged `add-image-semantic-search` branch (local + remote) — both deleted; local `main` fast-forwarded to the merge commit (`4c8e938`).

## 4. Validate

- [ ] 4.1 Run `openspec validate finalize-vision-embed-rollout --strict`
