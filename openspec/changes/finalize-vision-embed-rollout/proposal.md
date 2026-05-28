## Why

`vision-embed` is live and verified on PEA (GPU 7), but it is **not reachable through the prod LiteLLM proxy** (192.168.0.152), so clients can't actually call `heartcode-embed-vision`. Finalizing the rollout also means ranking the model with an offline eval and cleaning up after shelving BiQwen2.5. A blocker surfaced while preparing the prod deploy: the merged config routes **`heartcode-embed` → the shelved BiQwen (`:8100`, not running)**, while prod currently serves `heartcode-embed` from the **live legacy text-embed servers** (`:8090-8096`). Deploying the merged config as-is would **break the live text-embedding endpoint**, so the cutover must reconcile `heartcode-embed` first.

## What Changes

- **Prod LiteLLM cutover** (`ssh elm` / 192.168.0.152): reconcile `heartcode-embed` to a non-breaking target, deploy the config (`git pull` + restart — config is repo-mounted), and validate `heartcode-embed-vision` (text + image) end-to-end through the proxy.
- **Offline model eval**: rank `nomic-embed-vision-v1.5` vs `jina-clip-v2` / SigLIP2 on real photos (completes `serve-photo-embeddings` tasks 1.x); confirm or swap the default.
- **Cleanup**: prune the unused `local-ai-embed-mm` image + cached `Qwen2.5-VL-3B` base on PEA (~7 GB; keep `multimodal-embed/` code); update `docs/pea-server-setup.md`; delete the merged `add-image-semantic-search` branch.

## Capabilities

### New Capabilities
- `vision-embed-availability`: `heartcode-embed-vision` is reachable end-to-end through the prod LiteLLM proxy, and the deploy preserves a working `heartcode-embed` (no dead route).

### Modified Capabilities
<!-- None established in openspec/specs/. -->

## Impact

- **Prod LiteLLM restart** — brief proxy blip for all models on `192.168.0.152`.
- **`heartcode-embed` routing decision** — a live endpoint; merged config points it at the shelved BiQwen, must be repaired before deploy.
- **PEA disk** — reclaim ~7 GB (unused image + Qwen base).
- **Docs + branch** — `docs/pea-server-setup.md` refresh; delete merged branch.
