## Why

A repo audit on 2026-09-18 found that the stack runs well but the evidence around it has drifted. The SFW chat route no longer refuses adult content. CI never runs the unit tests: 10 of 228 fail on `main`, and 5 of those broke silently with the 429-queueing change. Prometheus alerts reach no one. CLAUDE.md contradicts `models.yaml`. 14 OpenSpec changes are still open, some untouched since May, so the specs describe a mix of past plans rather than the running system. The system is stable right now, which makes this a good time to reconcile the records with reality without touching production behavior.

## What Changes

- **SFW route alignment (priority only):** record `serve-aligned-sfw-chat-model` as the top-priority open change. This change adds no requirements for it; that change owns the work.
- **Unit tests gate CI:** add a pytest job to `gpu-build.yml` with pinned test dependencies. Fix the stale `metrics` stubs in `tests/test_gpu_health.py` (missing `inference_admission_total`), the embed-route pydantic failures, the known `test_backend_availability` failure and the missing `numpy` collection error, so the suite is green before it gates anything.
- **Alert delivery:** give PEA's Prometheus an Alertmanager with a Slack receiver (reusing the existing `#hardware-alerts` webhook) and prove delivery end to end with a synthetic alert. Reopen `enforce-capacity-guardrails` task 4.2, which is checked with no evidence while no Alertmanager exists.
- **Generated topology docs:** `render-config.py` writes the Models and Port Layout tables into a marked block in CLAUDE.md, and `--check` fails on drift. Fix the known stale claims at the same time: 2 image servers (the manifest has 1), 3 vision-embed and 3 text-embed deployments (the manifest has 2 each), and STT/TTS missing from the tables.
- **Stalled OpenSpec triage:** close or re-scope every open change using a read-only, docs-only procedure that brings the main specs in line with *deployed* behavior (see design.md). Delete the stale duplicate of the already-archived `prevent-load-induced-gpu-restarts`.
- **Repo clutter:** remove `generated-avatar.png` from the root. Merge the overlapping `gpu-server/` optimization and reliability notes into one doc. Document or retire the one-off compose files. Decide what happens to the non-Claude agent directories.

## Capabilities

### New Capabilities
- `unit-test-gating`: CI runs the gpu-server unit test suite on every push and pull request, with pinned dependencies, and fails on any test failure.
- `alert-delivery`: firing Prometheus alerts from PEA reach a human through Alertmanager, and delivery is verified end to end.
- `generated-topology-docs`: the CLAUDE.md model and port tables are generated from `gpu-server/models.yaml`, and CI fails when they drift.

### Modified Capabilities
<!-- None. Triage may archive other changes' deltas into main specs, but that is those changes' content, reconciled per design.md, not a requirement change owned here. -->

## Impact

- **Code:** `.github/workflows/gpu-build.yml`, `gpu-server/tests/`, a new `gpu-server/requirements-test.txt`, `gpu-server/scripts/render-config.py`, `gpu-server/configs/prometheus.yml`, a new Alertmanager service/config on PEA, `CLAUDE.md`.
- **Docs/specs:** every open change under `openspec/changes/`, and `openspec/specs/` through archiving.
- **Production:** only the alert-delivery work touches a running host. It adds a container and an `alerting:` block to Prometheus and changes nothing on the inference path. Triage and doc work make no changes to PEA or Prod.
