## 1. Manifest guard

- [ ] 1.1 Add `min_replicas` to the `models.yaml` schema and every model group; enforce in `render-config.py` (`--check` fails below minimum) with unit tests
- [ ] 1.2 Document the dated-reason rule for lowering `min_replicas` in CLAUDE.md

## 2. Placement truth

- [ ] 2.1 Write `scripts/check-placement.py` (live UUID/process/container mapping vs topology, pins, routing) with fixture-based tests
- [ ] 2.2 Add the check to `deploy.yml` after the GPU-host rolling restart and to the availability runbook

## 3. Canary tenancy

- [ ] 3.1 Topology schema v2 with optional `canary` per slot; update `gpu_failure_controller.py` to skip displaced services and alert; tests
- [ ] 3.2 Record the SFW canary on GPU 6 in `gpu-topology.json`

## 4. Alerts

- [ ] 4.1 Prometheus rules: cooldown events, 429/503 rate per model group, zero-success-with-traffic per model group over 1 h
- [ ] 4.2 Verify alert delivery with a synthetic cooldown on a canary deployment
