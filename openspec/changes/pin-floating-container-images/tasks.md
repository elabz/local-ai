## 1. Collect the running digests (read-only)

- [ ] 1.1 On PEA: `docker inspect` LocalAI, Prometheus, node-exporter, Grafana and record `RepoDigests` in design.md
- [ ] 1.2 On Prod: `docker inspect` the litellm Postgres and, if running, every Langfuse image; record the digests

## 2. Pin

- [ ] 2.1 Digest-pin the five floating images in `gpu-server/docker-compose.yml` and `litellm/docker-compose.yml`, each with a one-line comment naming its qualification test (LocalAI: image smoke test; Postgres: dump/restore)
- [ ] 2.2 Digest-pin `langfuse/docker-compose.yml`
- [ ] 2.3 `docker compose config` for every stack still renders; `check-memory-budget.py` unchanged

## 3. CI check

- [ ] 3.1 Add `gpu-server/scripts/check-image-pins.py` reading `docker compose config --format json` per stack; allowlist `^local-ai-`
- [ ] 3.2 Unit test: pass, tag-only failure naming stack and image, allowlisted local image
- [ ] 3.3 Run it in the `compose-validate` job for every stack

## 4. Scheduled refresh

- [ ] 4.1 Add `.github/dependabot.yml`: `docker` for `gpu-server/`, `litellm/`, `langfuse/`; `github-actions`; `pip` for `gpu-server/requirements-test.txt`; monthly; grouped per directory; `needs-qualification` label on LiteLLM, LocalAI and Postgres
- [ ] 4.2 Ignore major-version bumps for Postgres and Grafana in the config

## 5. Docs and proof

- [ ] 5.1 Document the pin-by-PR flow and the qualification comments in `CLAUDE.md` and `docs/pea-server-setup.md`
- [ ] 5.2 After merge: `docker compose up -d --dry-run` on PEA and Prod shows no recreate; record here with dates
- [ ] 5.3 Triage the first Dependabot batch; record what merged and what was held
