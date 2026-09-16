## 1. Manifest and compose

- [x] 1.1 Restore `gpu-server-5` in `gpu-server/docker-compose.yml` (UUID pin, `EXPECTED_GPU_UUID`, `CHAT_TEMPLATE_FILE`, port 8084, 8192m/9216m memcg) and replace the stale "DELIBERATELY GONE" comment _(commit 1553fcc)_
- [x] 1.2 Add `{gpu: 5, port: 8084}` to `heartcode-chat-nsfw` and `{gpu: 5, port: 8094}` to `heartcode-embed` in `models.yaml` with corrected comments; run `render-config.py` and confirm `--check` passes
- [x] 1.3 Update `configs/gpu-topology.json` slot `gpu-5` to `gpu-server-5` + `embedding-server-5` (ports 8084, 8094)
- [x] 1.4 Commit the parameterised `docker-compose.model-canaries.yml` and `scripts/model-canary-operations.sh` already running on PEA

## 2. Deploy and gate

- [x] 2.1 PEA: pull, render, `compose up -d gpu-server-5`; confirm `/health` on 8084 and process allocation < 6.6 GiB on `GPU-d8525241` _(2026-09-16: healthy after 36 s; llama-server 6,338 MiB + embed 234 MiB on GPU-d8525241)_
- [x] 2.2 Run ≥20 sequential completions directly against 8084; fail if any is empty or non-text; record the result in the change _(24 runs, 0 suspect, min 106 / avg 335 chars, 79 s total)_
- [x] 2.3 Prod: pull and restart LiteLLM; verify two `heartcode-chat-nsfw` deployments and a completion routed to `heartcode-gpu5` _(`compose up -d` did not restart the proxy because config.yaml is a bind mount; `compose restart litellm` was required. `/model/info` now lists heartcode-gpu4 + heartcode-gpu5 and heartcode-embed1 + heartcode-embed2.)_
- [ ] 2.4 PEA: set `SFW_CANARY_CONTAINER=pea-sfw-model-canary-gpu6` in `.env` and recreate the canary; confirm 18085 healthy on `GPU-fe0fc635` _(BLOCKED 2026-09-16: `.env` updated and the container recreated under the new name, but removing the old container freed port 18085, which let the GPU failure controller's stale inventory (`/var/lib/pea-gpu-controller/current-inventory.json`, copied from the topology on 2026-09-11) succeed at `compose up qwen3-canary embedding-server-5` and `compose up gpu-server-6 dino-embed-2` on its next 60 s cycle. GPU 6 is back to its production layout (pea-gpu-6 :8085 + dino-2 :8105, both healthy, unrouted) and the SFW canary OOMs on load. `qwen3-canary-gpu5` crash-loops on GPU 5 every cycle (OOM against pea-gpu-5, ~84 MiB per attempt). Needs root: copy the new `configs/gpu-topology.json` over the controller inventory and restart `pea-gpu-controller`, then decide GPU 6: keep NSFW (route 8085 + 8105) or re-pin the canary and record it in the inventory — see `enforce-capacity-guardrails`.)_

## 3. Docs

- [x] 3.1 Update CLAUDE.md port/GPU tables and the NSFW replica count
