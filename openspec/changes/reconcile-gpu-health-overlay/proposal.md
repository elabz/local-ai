# Reconcile the GPU health overlay with the plain deploy

## Why

PEA runs two different configurations of the same chat and embed services depending on who last started them. A plain deploy (`docker compose up -d`, `deploy.yml`, the rolling rollout) starts every chat and embed container with `GPU_HEALTH_ENABLED=0` and the `:latest` embed images. When `gpu_failure_controller.py` restores a card, it layers `docker-compose.gpu-health-canary.yml` onto its `compose up`, so that slot comes back with the gate **on** and the `:gpu-health-preflight` embed images. Found 2026-09-18 (`project-health-improvements` 6.3) and recorded in `gpu-server/README.md` as a mixed-state hazard; nothing tests for it and nothing reconciles it, so the fleet drifts every time a card fails.

The `gpu-fault-health` spec already requires readiness to prove current device usability on **every** GPU backend. Today that requirement is only true on slots the controller has touched.

## What Changes

- **One configuration for every start path.** The GPU health gate and the embed image tag become the same whether a service is started by a plain deploy or by the failure controller. The overlay file is either folded into `docker-compose.yml` (gate on by default, one image tag) or deleted and the controller stops passing it.
- **Retire the `:gpu-health-preflight` tag.** The embed images that carry the readiness probe become the `:latest` build; a single Dockerfile per embed service produces one image.
- **Drift check.** A read-only script (and a unit test over the compose files) fails when the controller's effective compose config for a slot differs from the plain deploy's for the same slot in `GPU_HEALTH_ENABLED` or `image`. It joins `check-placement.py` in the deploy preflight.
- **Reconcile the live fleet** with a rolling, health-gated recreate of every slot that `docker inspect` shows in the overlay state, then prove a plain deploy is a no-op.
- Update `gpu-server/README.md` (remove the hazard banner, delete the overlay row or reword it) and the availability runbook.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `gpu-fault-health`: adds a requirement that the readiness gate configuration is identical across every start path, and that this is checked before deploy. Existing requirements are unchanged (ADDED delta only).

## Impact

- `gpu-server/docker-compose.yml` (default `GPU_HEALTH_ENABLED`, embed image tags), `gpu-server/docker-compose.gpu-health-canary.yml` (folded in or removed), `gpu-server/scripts/gpu_failure_controller.py` (compose file list), `gpu-server/vision-embed/` and `gpu-server/dino-embed/` build tags, `gpu-server/scripts/check-placement.py` or a sibling drift script, `gpu-server/tests/test_gpu_failure_controller.py`, `.github/workflows/deploy.yml`, `gpu-server/README.md`, `docs/gpu-inference-availability-runbook.md`.
- Live hosts: every PEA chat and embed container is recreated once, one slot at a time, via the `pea-rolling-rollout` procedure. The shared-GPU neighbour of a recreated slot may be recreated too (controller behaviour, see the `GPU controller recreates whole slots` memory); the rollout must account for it.
- Risk: turning the gate on fleet-wide with `GPU_HEALTH_ENABLED=1` re-enables readiness probes on cards that never ran them since the 2026-09-18 `GPUReadinessLost` false positive fix; the alert rules must be re-verified against a gated fleet.
