## Context

`gpu-server/docker-compose.yml` sets `GPU_HEALTH_ENABLED: ${GPU_HEALTH_ENABLED:-0}` on all six chat workers and four embed servers, and the embed services use `local-ai-vision-embed:latest` / `local-ai-dino-embed:latest`. `docker-compose.gpu-health-canary.yml` overrides exactly those ten services: gate `"1"` everywhere, embed images retagged `:gpu-health-preflight`. Only `scripts/gpu_failure_controller.py` (line ~200) passes that overlay, on every compose action it runs to restore a card, together with a generated UUID override.

So the fleet has two stable states per slot, and which one a slot is in depends on its failure history. `alert_rules.yml` was already adjusted once (c942ef5, 2026-09-18) because the readiness gauge is never set when the gate is off; that fix assumed the gate is off by default, which is only true until the next card failure.

Constraints: PEA hosts are shared 8 GB cards at ~7.4 to 7.5 GB; the controller recreates whole slots, not single services; deploys must stay no-ops when nothing changed (`pea-rolling-rollout`); GPU 5 stays quarantined from the chat route.

## Goals / Non-Goals

**Goals:**
- Exactly one effective compose configuration per slot, regardless of start path.
- One image per embed service (no parallel `:gpu-health-preflight` build).
- A pre-deploy check that fails on drift between the controller's compose invocation and the plain deploy's.
- The live fleet reconciled to that one configuration with a plain deploy proven to be a no-op afterwards.

**Non-Goals:**
- Changing what the readiness gate probes or its thresholds (that is `gpu-fault-health` as specified).
- Changing the controller's recovery algorithm, UUID override or Slack escalation.
- Touching the model-canary compose file, which is a genuine opt-in overlay.

## Decisions

**D1. Gate on by default, overlay deleted.** Fold `GPU_HEALTH_ENABLED=1` into `docker-compose.yml` as the default and delete the overlay; the controller passes only the base compose files plus its UUID override. Alternative: gate off everywhere and make the controller stop passing the overlay. Rejected because the `gpu-fault-health` spec requires readiness to prove device usability on every backend, and the 2026-09-18 alert fix was a workaround for the gate being off, not a decision to keep it off. Alternative: keep the overlay and make the plain deploy pass it too. Rejected: two files that must be passed together is the same hazard one deploy script away.

**D2. The readiness-probe embed build becomes `:latest`.** Confirm what differs between the `:gpu-health-preflight` and `:latest` embed images (a Dockerfile target, an env default, or nothing). If the probe code is already in the `:latest` source, retag; if not, merge the difference into the one Dockerfile. Either way `deploy.yml` and `setup-pea.sh` build one tag per embed service and the preflight tag is removed from the registry on PEA.

**D3. Drift check compares rendered compose, not file text.** Extend `scripts/check-placement.py` (or add `check-start-path-parity.py`) to run `docker compose config` with the plain deploy's file list and with the controller's file list for a given slot and diff `environment.GPU_HEALTH_ENABLED` and `image` for every chat/embed service. A unit test exercises it against the checked-in compose files with a stubbed `compose config`. It runs in CI's `compose-validate` job (no LAN needed) and in `deploy.yml`'s preflight.

**D4. Reconcile with the rolling rollout, slot by slot.** For each slot, `docker inspect` the chat and embed containers; if either shows the overlay state (or, after D1, the pre-D1 state), recreate the whole slot with `--force-recreate`, wait for `/health`, then move on. Never two replicas of the same route at once. Finish with `docker compose up -d --dry-run` showing no changes.

**D5. Re-verify alerts against a gated fleet before the rollout.** `GPUReadinessLost` (c942ef5) and the readiness gauge semantics must be re-run in promtool tests with the gate on, since the gauge will now be set on every backend.

## Risks / Trade-offs

- [Gate on fleet-wide adds a periodic bounded GPU execution probe to every backend] → the probe already runs on any controller-touched slot today with no recorded incident; measure TTFT on one slot for 24 h before rolling the rest (the `prompt-cache-ttft.py` script exists).
- [The preflight image differs from `:latest` in more than the probe] → D2 starts with an image diff (`docker history`, Dockerfile targets) before retagging; nothing is deleted until the merged image passes `/health` on one embed slot.
- [Recreating a slot on GPU 1-2 or 3/6 restarts a chat replica and its embed neighbour together] → one slot at a time, `min_replicas` floors stay satisfied because the other two SFW replicas and the other NSFW replica stay up.
- [Controller runs mid-rollout and recreates a slot with the old file list] → stop `pea-gpu-controller.service` for the rollout window, restart it after the overlay-free controller code is deployed.

## Migration Plan

1. Land D1 to D3 in one PR; CI must be green (compose-validate, unit tests, drift check).
2. On PEA: `git pull`, rebuild the embed images under the one tag, stop the controller service.
3. Rolling recreate per D4, `pea-rolling-rollout` procedure, `/health` gating.
4. Restart the controller service; simulate a restore on one slot (dry-run mode if available) and confirm the effective config matches.
5. `docker compose up -d --dry-run` is a no-op; record evidence in `tasks.md`.

Rollback: the previous compose files are one `git checkout` away; the overlay-state containers keep serving until recreated, so a rollback is a second rolling recreate, not an outage.

## Open Questions

- Does the `:gpu-health-preflight` image actually differ in source from `:latest`, or was it only ever a build of the same Dockerfile at a different commit? Resolved by D2's first task.
- Did the 2026-09-18 alert-rule fix assume the gate off in any rule other than `GPUReadinessLost`? Check `alert_rules.yml` for every `gpu_ready`-style series.
