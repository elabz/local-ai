## 1. Manifest and compose

- [ ] 1.1 Restore `gpu-server-5` in `gpu-server/docker-compose.yml` (UUID pin, `EXPECTED_GPU_UUID`, `CHAT_TEMPLATE_FILE`, port 8084, 8192m/9216m memcg) and replace the stale "DELIBERATELY GONE" comment
- [ ] 1.2 Add `{gpu: 5, port: 8084}` to `heartcode-chat-nsfw` and `{gpu: 5, port: 8094}` to `heartcode-embed` in `models.yaml` with corrected comments; run `render-config.py` and confirm `--check` passes
- [ ] 1.3 Update `configs/gpu-topology.json` slot `gpu-5` to `gpu-server-5` + `embedding-server-5` (ports 8084, 8094)
- [ ] 1.4 Commit the parameterised `docker-compose.model-canaries.yml` and `scripts/model-canary-operations.sh` already running on PEA

## 2. Deploy and gate

- [ ] 2.1 PEA: pull, render, `compose up -d gpu-server-5`; confirm `/health` on 8084 and process allocation < 6.6 GiB on `GPU-d8525241`
- [ ] 2.2 Run ≥20 sequential completions directly against 8084; fail if any is empty or non-text; record the result in the change
- [ ] 2.3 Prod: pull and restart LiteLLM; verify two `heartcode-chat-nsfw` deployments and a completion routed to `heartcode-gpu5`
- [ ] 2.4 PEA: set `SFW_CANARY_CONTAINER=pea-sfw-model-canary-gpu6` in `.env` and recreate the canary; confirm 18085 healthy on `GPU-fe0fc635`

## 3. Docs

- [ ] 3.1 Update CLAUDE.md port/GPU tables and the NSFW replica count
