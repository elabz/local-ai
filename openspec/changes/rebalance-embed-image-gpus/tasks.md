## 1. docker-compose

- [x] 1.1 Replace the dedicated `vision-embed` (GPU 7) with 3 co-located `vision-embed-{1,2,3}` on SFW chat GPUs 1-3 (`GPU-76bfe17d`/`f1fa6009`/`1f2ba781`), ports `:8101-8103` — done; `MAX_BATCH_SIZE=4`, mem_limit 2560m each
- [x] 1.2 Remove text-embed on GPU 1-3 (`embedding-server-1/2/3`); keep `embedding-server-4/5/6` (GPU 4-6, `:8093-8095`) — done
- [x] 1.3 Add `image-server-2` on GPU 7 (`GPU-f417c539`), port `:5101`, sharing `image_backends` + `models` volumes — done
- [x] 1.4 Update layout/budget header comments — done (compose header + budget)

## 2. PEA deploy (staged)

- [ ] 2.1 Stop `pea-embed-1/2/3` + `pea-embed-vision-1`
- [ ] 2.2 `docker compose up -d vision-embed-1 vision-embed-2 vision-embed-3`; verify health + dim 768 on each (`:8101-8103`); confirm SFW chat still healthy (VRAM)
- [ ] 2.3 `docker compose up -d image-server-2`; verify it reuses the backend (fast start) and generates an image on `:5101`
- [ ] 2.4 Confirm full `docker compose ps` healthy

## 3. LiteLLM cutover

- [x] 3.1 Update `litellm/config.yaml`: `heartcode-embed-vision` → `:8101-8103` (3), `heartcode-embed` → `:8093-8095` (3), `heartcode-image` → `:5100,:5101` (2); rate limits retuned; header refreshed
- [ ] 3.2 Commit + push + merge to main
- [ ] 3.3 `ssh elm`: `git pull origin main`; restart LiteLLM; validate all three model names through the proxy
- [ ] 3.4 Confirm rollback path

## 4. Monitoring & docs

- [ ] 4.1 Update `prometheus.yml` (scrape the 3 vision + 2 image targets) + `gpu-watchdog.sh` GPU→container map
- [ ] 4.2 Update `CLAUDE.md` + `docs/pea-server-setup.md` (new layout)
- [ ] 4.3 Run `openspec validate rebalance-embed-image-gpus --strict`
