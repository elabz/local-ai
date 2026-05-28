## Context

`vision-embed` (nomic-embed-vision-v1.5 + text-v1.5, 768-d) is compose-managed and healthy on PEA GPU 7 (`:8101`), verified 2026-05-28. The prod LiteLLM proxy (`ssh elm`, 192.168.0.152) mounts `litellm/config.yaml` from its git checkout (`./config.yaml:/app/config.yaml:ro`, `--config /app/config.yaml`), so a `git pull` + container restart picks up config changes. Prod is on `main@2bf4c17` (pre-cutover); its live config routes `heartcode-embed` to 7 legacy text-embed servers (`:8090-8096`). `origin/main` (merged) routes `heartcode-embed` → `:8100` (shelved BiQwen) and adds `heartcode-embed-vision` → `:8101`.

## Goals / Non-Goals

**Goals:**
- Make `heartcode-embed-vision` callable through the prod proxy (text + image).
- Do not break the live `heartcode-embed` endpoint during the deploy.
- Confirm the chosen model with an offline eval; leave the repo/host clean.

**Non-Goals:**
- Reviving BiQwen2.5 / completing the `switch-to-nomic` cutover.
- Vector storage / search (downstream).
- Decommissioning the legacy text-embed servers (separate decision).

## Decisions

### Decision 1: Reconcile `heartcode-embed` before deploying (the blocker)
The merged config points `heartcode-embed` at the shelved `:8100`. Options:
- **(a) Restore legacy** — point `heartcode-embed` back at the live text-embed servers (`:8090-8095`, 6 of the original 7; `:8096`/embed-7 was removed). **Non-breaking, status-quo-preserving.** Recommended unless the endpoint is being retired.
- **(b) Alias → vision** — `model_group_alias: heartcode-embed → heartcode-embed-vision`. Consolidates onto one service (both use nomic text-v1.5, 768-d), but changes text behavior (vision applies the `search_query:` prefix) and couples old callers to the new model.
- **(c) Remove** — drop `heartcode-embed`; force callers onto `heartcode-embed-vision`. Breaking for existing text-embed callers.

This is a live-endpoint policy call (depends on who still calls `heartcode-embed`), so it is confirmed with the user (task 1.1) before deploy.

### Decision 2: Deploy via git pull + compose restart on prod
Config is repo-mounted, so: `git pull origin main` on `elm`, then `docker compose up -d litellm` (recreate to reload config). Brief proxy blip. **Rollback:** `git checkout <prev> -- litellm/config.yaml` (or revert the reconciliation) + restart.

### Decision 3: Cleanup keeps code, reclaims runtime artifacts
Prune the unused `local-ai-embed-mm` image and the `Qwen2.5-VL-3B` HF snapshot on PEA (~7 GB) — re-downloadable if BiQwen is ever revived. Keep `multimodal-embed/` source. Refresh `docs/pea-server-setup.md`; delete the merged feature branch.

## Risks / Trade-offs

- **Deploy breaks `heartcode-embed`** → reconcile first (Decision 1); validate the endpoint post-restart, not just vision.
- **Proxy restart blip** → all models drop for a few seconds; do it in one quick recreate.
- **Eval picks a different model** → then redeploy vision service with the new model + re-point `:8101`.
- **Pruning Qwen base** → BiQwen revival re-downloads ~7 GB; acceptable since shelved.

## Migration Plan

1. Reconcile `heartcode-embed` in `litellm/config.yaml` per the user's choice; commit to a branch + PR (or main).
2. `ssh elm`: `git pull origin main`; `docker compose up -d litellm`.
3. Validate: proxy `/health`; `heartcode-embed-vision` text + image → 768-d; `heartcode-embed` still returns vectors.
4. Cleanup (prune, docs, branch). **Rollback:** revert config + restart litellm.

## Open Questions

- **`heartcode-embed` disposition** — restore-legacy (a), alias→vision (b), or remove (c)? (Decision 1.)
- **Offline eval outcome** — does `nomic-embed-vision-v1.5` hold as default vs `jina-clip-v2`/SigLIP2?
- **Decommission legacy text-embed servers** — out of scope here; revisit once `heartcode-embed` disposition is settled.
