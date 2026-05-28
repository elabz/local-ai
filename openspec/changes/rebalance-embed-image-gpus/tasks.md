## 1. docker-compose

- [x] 1.1 Replace the dedicated `vision-embed` (GPU 7) with 3 co-located `vision-embed-{1,2,3}` on SFW chat GPUs 1-3 (`GPU-76bfe17d`/`f1fa6009`/`1f2ba781`), ports `:8101-8103` — done; `MAX_BATCH_SIZE=4`, mem_limit 2560m each
- [x] 1.2 Remove text-embed on GPU 1-3 (`embedding-server-1/2/3`); keep `embedding-server-4/5/6` (GPU 4-6, `:8093-8095`) — done
- [x] 1.3 Add `image-server-2` on GPU 7 (`GPU-f417c539`), port `:5101`, sharing `image_backends` + `models` volumes — done
- [x] 1.4 Update layout/budget header comments — done (compose header + budget)

## 2. PEA deploy (staged)

- [x] 2.1 Stop `pea-embed-1/2/3` + `pea-embed-vision-1` (old dedicated) — removed
- [x] 2.2 Started `vision-embed-1/2/3` (`:8101-8103`) — all healthy, dim 768; SFW chat healthy. GPU 1-3 at **~7.4 GB/8 GB** (chat + vision; tight but stable)
- [x] 2.3 Started `image-server-2` — reused the shared cuda12-diffusers backend (no re-download); generated an image on `:5101` (GPU 7 → ~6 GB SSD-1B loaded)
- [x] 2.4 Full `docker compose ps` — 16 services healthy

## 3. LiteLLM cutover

- [x] 3.1 Update `litellm/config.yaml`: `heartcode-embed-vision` → `:8101-8103` (3), `heartcode-embed` → `:8093-8095` (3), `heartcode-image` → `:5100,:5101` (2); rate limits retuned; header refreshed
- [x] 3.2 Commit + push + merge to main — PR #4 (`962d2a1`)
- [x] 3.3 `ssh elm` pull + restart LiteLLM — validated through proxy: `heartcode-embed-vision` text+image → 768-d, `heartcode-embed` text → 768-d, `heartcode-image` gen → 200 (load-balanced)
- [x] 3.4 Rollback path — `git checkout <prev> -- litellm/config.yaml` + restart litellm (and restore compose + restart PEA services) restores prior layout

## 4. Monitoring & docs

- [x] 4.1 Update `prometheus.yml` (3 vision + 2 image targets) + `gpu-watchdog.sh` GPU→container map (corrected to `pea-*` names + new layout)
- [ ] 4.2 Update `CLAUDE.md` + `docs/pea-server-setup.md` for the rebalanced layout — **pending**: both still describe GPU 7 = dedicated vision + 1 image server; need: vision co-located GPU 1-3, text-embed GPU 4-6, 2 image servers (GPU 7-8)
- [x] 4.3 Run `openspec validate rebalance-embed-image-gpus --strict` — valid
