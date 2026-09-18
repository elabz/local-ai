# Proposal: enforce-capacity-guardrails

## Why

Capacity was lost silently: canaries displaced two of three NSFW replicas, routing dropped to one deployment, the placement records drifted from reality, and every health check stayed green through three weeks of zero successful NSFW inference. Nothing in CI, the manifest, or monitoring encodes "how many replicas a model group needs" or "does the recorded placement match the running one".

## What Changes

- **Minimum replicas in the manifest**: each `models.yaml` model group declares `min_replicas`; `render-config.py --check` fails when the routed deployment count is below it, so a canary or maintenance change that drops routing is a deliberate, reviewed edit.
- **Placement truth check**: a script compares `configs/gpu-topology.json` and the compose UUID pins against live `nvidia-smi` process → UUID mapping and container names on PEA, and reports drift (wrong card, stopped tenant, unrouted running replica). Run by the deploy workflow and available as a runbook step.
- **Canary tenancy is recorded**: the topology schema gains an optional `canary` field per slot so a canary from the second compose file can be represented, and the GPU failure controller SHALL NOT restart a slot's main-compose services while a canary is recorded there.
- **Capacity alerts**: LiteLLM deployment cooldown events, 429/503 rate per model group, and "successful completions per model group over 1 h == 0 while requests > 0" alert to the operator channel.

## Capabilities

### New Capabilities

- `capacity-manifest`: minimum replica declarations, routed-count validation, placement drift detection, canary tenancy recording.

### Modified Capabilities

- `gpu-inference-availability`: alerting covers cooldown events and zero-success windows per model group, not only restarts and 5xx.
- `gpu-fault-health`: the failure controller respects recorded canary tenancy when recovering a slot.

## Impact

- `gpu-server/models.yaml` schema + `scripts/render-config.py`, new `scripts/check-placement.py`, `configs/gpu-topology.json` schema v2, `scripts/gpu_failure_controller.py`, `monitoring/prometheus` alert rules, `.github/workflows/deploy.yml` (placement check step), docs runbook.

## Non-goals

- No automatic re-placement or self-healing of capacity; the guardrails block and alert, humans decide.
- No change to canary evaluation procedure itself.
- **No alert delivery path.** This change writes and deploys the rules; it does not build the channel that carries them. Verified 2026-09-18: PEA's Prometheus has no `alerting:` block and zero active/dropped alertmanagers, and no Alertmanager runs on PEA or Prod, so "alert to the operator channel" today means "visible in the Prometheus UI and Grafana". Standing up Alertmanager and a receiver needs its own change; until then these rules detect capacity loss but do not announce it.
