## 1. Decision

- [ ] 1.1 Confirm with the owner: provision the runner (default) or retire the workflow; record the decision and date in design.md. If retired, skip to section 6

## 2. Workflow

- [ ] 2.1 Derive the gpu-server restart order from `models.yaml` (SFW/NSFW alternating; skip GPUs absent from every chat group); refuse slots marked recovering in the controller inventory
- [ ] 2.2 Bounded `/health` wait per replica; abort on first failure; final `docker compose up -d --dry-run` must report no change
- [ ] 2.3 Add `target: probe` (LiteLLM health check only) and a weekly `schedule:` trigger that uses it
- [ ] 2.4 Optionally add `actionlint` to CI's `python-lint` job or a new `workflow-lint` job; CI green

## 3. Runner and repo settings (user at the keyboard)

- [ ] 3.1 Hand over the steps: dedicated user on Prod, runner install per `docs/pea-server-setup.md`, `svc.sh install`, docker group, Prod→PEA SSH key restricted to the deploy user
- [ ] 3.2 Create the `production` Environment with the owner as required reviewer; set `DEPLOY_DIR`, `LITELLM_HEALTH_URL`, `GPU_SERVER_HOST`, `GPU_SERVER_USER`, `GPU_SERVER_SSH_KEY`
- [ ] 3.3 Runner shows online under repo Settings → Actions → Runners with the `homelab` label

## 4. Proof

- [ ] 4.1 Dispatch `litellm` with the SHA Prod already runs; job green; `docker compose up -d --dry-run` on Prod unchanged; record run URL here
- [ ] 4.2 Dispatch `gpu-server` with the SHA PEA already runs; every replica restarted in order and healthy; final dry-run no-op; record run URL and per-replica timings
- [ ] 4.3 Dispatch `probe`; then wait for the first scheduled probe and record its result

## 5. Docs

- [ ] 5.1 Rewrite the CI/CD section of `CLAUDE.md`: `deploy.yml` is the path, manual steps are the fallback, the probe and what its failure means
- [ ] 5.2 Update `docs/pea-server-setup.md` CD section and the `pea-rolling-rollout` skill to point at the workflow for routine deploys

## 6. Retirement path (only if 1.1 declines)

- [ ] 6.1 Delete `.github/workflows/deploy.yml`; remove the runner section from `docs/pea-server-setup.md`
- [ ] 6.2 Rewrite the CD parts of `CLAUDE.md` around the manual procedure and `pea-rolling-rollout`
- [ ] 6.3 Replace this change's `cd-deploy` spec with a note recording the decision, then archive with `--skip-specs`
