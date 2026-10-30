## 1. Establish the facts

- [ ] 1.1 Diff the `:gpu-health-preflight` and `:latest` vision-embed and dino-embed images on PEA (`docker history`, image labels, Dockerfile targets) and record in design.md whether the source differs
- [ ] 1.2 `docker inspect` every chat and embed container on PEA; record which slots are in the overlay state (gate on, preflight image) in `evidence/pre-state.md`
- [ ] 1.3 Grep `gpu-server/configs/alert_rules.yml` and its promtool tests for every readiness series; list the rules whose semantics assumed the gate off

## 2. One configuration

- [ ] 2.1 Set `GPU_HEALTH_ENABLED` default to `1` in `gpu-server/docker-compose.yml` for the six chat and four embed services
- [ ] 2.2 Fold any real source difference from 1.1 into the single vision-embed and dino-embed Dockerfiles; build tag stays `:latest`
- [ ] 2.3 Delete `gpu-server/docker-compose.gpu-health-canary.yml`; remove it from `gpu_failure_controller.py`'s compose file list, keeping the generated UUID override
- [ ] 2.4 Update `tests/test_gpu_failure_controller.py` for the new file list; add a case asserting the controller never passes a second compose overlay
- [ ] 2.5 Re-run the promtool alert tests with the gate on; adjust any rule found in 1.3 and add a test for the gated case

## 3. Drift check

- [ ] 3.1 Add a start-path parity check (extend `check-placement.py` or add `check-start-path-parity.py`) that renders both compose invocations and diffs gate and image per chat/embed service
- [ ] 3.2 Unit test: identical configs pass; an overlay with a different image or gate fails naming the service and field
- [ ] 3.3 Wire the check into CI `compose-validate` and the `deploy.yml` gpu-server preflight

## 4. Docs

- [ ] 4.1 Remove the mixed-state hazard banner and the overlay row from `gpu-server/README.md`; describe the single configuration
- [ ] 4.2 Update `docs/gpu-inference-availability-runbook.md` and `CLAUDE.md` where they mention the overlay or `GPU_HEALTH_ENABLED=0`

## 5. Reconcile the live fleet

- [ ] 5.1 Merge after green CI; on PEA `git pull`, rebuild the embed images, `systemctl stop pea-gpu-controller.service`
- [ ] 5.2 Measure TTFT on one recreated slot for 24 h with `scripts/prompt-cache-ttft.py`; record in `evidence/`
- [ ] 5.3 Rolling recreate of every remaining slot (`pea-rolling-rollout`), one at a time, `/health` gated, never two replicas of one route
- [ ] 5.4 Restart the controller service; exercise one restore path and confirm `docker inspect` matches a plain-deploy container
- [ ] 5.5 `docker compose up -d --dry-run` is a no-op; remove the `:gpu-health-preflight` images from PEA; record evidence and dates here
