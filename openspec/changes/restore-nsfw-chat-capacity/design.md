# Design: restore-nsfw-chat-capacity

## Context

Live state verified on PEA 2026-09-16 via `nvidia-smi` process listing: GPUs 1-4 serve chat as documented; GPU 5 (UUID `GPU-d8525241`) holds only `pea-embed-5` (234 MiB); GPU 6 (`GPU-fe0fc635`) holds the SFW canary process (7,588 MiB) under the container name `pea-sfw-model-canary-gpu5`; `pea-gpu-6` and `pea-embed-dino-2` exited 11 days ago; the NSFW canary on 18086 is not running. PEA's `.env` pins the SFW canary to GPU 6 deliberately because a 12B occupant measures 7,567 MiB, inside GPU 5's corruption margin. The Lumimaid Q5_K_M production replica measures 6,368 MiB on GPU 4 with 16K context and Q8 KV.

## Goals / Non-Goals

**Goals:** two routed NSFW replicas; every recorded placement true; no production regression on GPUs 1-4, 7, 8.

**Non-Goals:** admission/cooldown changes; touching the SFW canary's card; changing the quarantine rule.

## Decisions

1. **Restore on GPU 5 at production config rather than reclaim GPU 6.** GPU 6 is the only card qualified for >7.5 GiB canaries and the canary queue is not empty. GPU 5 previously served this exact workload; 6.4 GiB is comfortably under the 7.6 GiB fault region. *Rejected:* Q4_K_M on GPU 5 for extra margin — the margin is already >1 GiB and Q4 would make the two NSFW replicas behave differently.
2. **Gate on generation, not load.** The fault manifests as corrupt or empty generations after a successful load, so the restore script runs ≥20 sequential direct completions against 8084 and fails the restore if any is empty or non-text before models.yaml routes it.
3. **Compose definition follows the current sibling pattern**: UUID pin (`PEA_GPU_5_UUID`), `EXPECTED_GPU_UUID`, `CHAT_TEMPLATE_FILE`, and the 8192m/9216m memcg limits that GPU 4 required after memcg kills.
4. **Topology file records main-compose tenants only.** `gpu_failure_controller.py` stops/starts `slot.services` via the main compose file, so a canary from the second compose file cannot be listed as a service there. GPU 5 is corrected to `gpu-server-5` + `embedding-server-5`. GPU 6's entry keeps its stopped tenants (the controller hazard of restarting them against a canary is recorded in `enforce-capacity-guardrails`).
5. **Commit the parameterised canary compose/script** that PEA already runs (byte-identical uncommitted diffs on PEA and the workstation), so the deployed state is reproducible from git.

## Risks / Trade-offs

- [GPU 5 corruption region is approximate] → generation gate before routing; monitor empty-response rate on 8084 for the first day; roll back by removing the deployment line and `compose stop gpu-server-5`.
- [Host RAM] → 14 GiB available; a chat container uses ~1.5 GiB RSS with an 8 GiB ceiling.
- [Canary rename recreates the container] → ~1 min canary downtime, no production route affected.

## Migration Plan

1. Commit compose/manifest/topology changes; `render-config.py --check` green.
2. PEA: `git pull`, render, `compose up -d gpu-server-5`, wait healthy, run the generation gate.
3. Prod: `git pull`, `compose up -d litellm` (config is a bind mount; restart required), verify `/v1/models` and a routed completion hits `heartcode-gpu5`.
4. PEA: set `SFW_CANARY_CONTAINER=pea-sfw-model-canary-gpu6`, recreate the canary.
Rollback: revert the commit, restart LiteLLM, `compose stop gpu-server-5`.

## Open Questions

- Whether GPU 6 returns to NSFW duty when the current canary queue is exhausted (decision belongs to the canary change).
