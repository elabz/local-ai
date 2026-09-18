# Design: enforce-capacity-guardrails

## Context

`render-config.py` already validates the manifest deterministically and runs in CI (`model-manifest-validate`). `gpu_failure_controller.py` reads `gpu-topology.json` (`services`, `containers`, `ports`) and will `compose up` a slot's services on recovery — which, for GPU 6 today, would start the stopped NSFW replica and DINO embed against the canary and OOM the card. Prometheus and Grafana run on PEA; LiteLLM exposes Prometheus metrics with per-deployment failure/cooldown counters.

## Decisions

1. **`min_replicas` lives in the manifest**, validated in the same script CI already runs; no new CI job. Default 2 for chat and embed groups, 1 for image/speech.
2. **Placement check is a standalone script** (`scripts/check-placement.py`) using `nvidia-smi --query-compute-apps` and `docker inspect` (both already used by the controller), pure stdlib, unit-tested with recorded fixtures. Deploy workflow runs it over SSH after the rolling restart.
3. **Topology schema v2** adds `canary: {container, compose_file, uuid}`; controller checks it before `compose up`. `schema_version` bump with backward-compatible reader.
4. **Alerts in Prometheus rules** using LiteLLM's `litellm_deployment_cooled_down_total`, `litellm_deployment_failure_responses`, and success counters; the zero-success rule is `increase(requests) > 0 and increase(success) == 0` over 1 h.

## Risks / Trade-offs

- [`min_replicas` blocks a legitimate emergency removal] → lowering it with a dated comment is a one-line edit in the same PR.
- [Placement check needs host access] → runs only on the GPU-host deploy target and the runbook; CI on GitHub runners skips it.

## Migration Plan

Add `min_replicas` to every group at its current routed count (NSFW at 2 after `restore-nsfw-chat-capacity`), then raise where policy demands. Ship the controller change with a unit test before editing the live topology.

## Open Questions

- Threshold values for the 429/503 rate alert.
