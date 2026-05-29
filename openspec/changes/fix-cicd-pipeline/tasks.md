## 1. Stop the failures — rewrite CI (GitHub-hosted, no LAN/secrets)

- [x] 1.1 In `.github/workflows/gpu-build.yml`, remove the GHCR push step and the `appleboy/ssh-action` "Deploy to GPU servers" step (neither works from a cloud runner).
- [x] 1.2 Add a top-level/per-job `permissions:` block (validation jobs `contents: read`); bump `actions/checkout`→v5 and `docker/*` actions to current majors + `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` to clear the deprecation annotation.
- [x] 1.3 Add `compose-validate` job: run `docker compose -f <stack>/docker-compose.yml config -q` for `gpu-server`, `litellm`, `monitoring`, `langfuse`. Auto-touches `env_file:` targets and auto-injects dummy values for hard-required `${VAR:?}` vars (verified locally for all stacks; monitoring has no compose file → skipped).
- [x] 1.4 Add `litellm-validate` job (`litellm/validate_config.py`): parse `config.yaml` + `config-local.yaml`; assert `model_list` non-empty, every `litellm_params` has `api_base`, and **unique `model_info.id`** (corrected from "unique `model_name`" — LiteLLM intentionally repeats `model_name` per load-balanced deployment, so id is the right key).
- [x] 1.5 Add `python-lint` job: `ruff check` (real-errors gate `E9,F63,F7,F82` + advisory full pass) + `python -m py_compile` over `gpu-server/*.py`, `vision-embed/*.py`, `dino-embed/*.py`.
- [x] 1.6 Convert the image build to a path-filtered **build-only** `gpu-build` job (`push: false`, `cache-from/to: gha`), gated via a `changes` job (`dorny/paths-filter`) on `gpu-server/Dockerfile`, `gpu-server/requirements.txt`, or wrapper `*.py` changes.
- [x] 1.7 Add `concurrency` (cancel-in-progress per ref) so rapid pushes don't queue duplicate 13-min builds.
- [x] 1.8 Verified on PR #11: run is **green** (all 5 validation jobs pass, `gpu-build` path-skipped), no GHCR/SSH steps, and **no Node-20 deprecation annotation** (bumped to `setup-python@v6` + `paths-filter@v4`).

## 2. Model manifest + generator (zero-diff cutover)

- [x] 2.1 Define `gpu-server/models.yaml`: per served model — `api_name`, `aliases`, `kind` (`chat`/`text-embed`/`vision-embed`/`visual-embed`/`image`), `deployments` (GPU index + port), `source`, routing knobs (`rate_limit`, `params`). Populated to describe the **current** topology exactly (6 models, 14 deployments).
- [x] 2.2 Extract hand-maintained LiteLLM router/general/litellm settings into `litellm/config.base.yaml` (everything except `model_list` + the generated `model_rate_limits`/`model_group_alias`).
- [x] 2.3 Write `gpu-server/scripts/render-config.py` (stdlib + `PyYAML`, deterministic): renders **`gpu-server/models.generated.env`** (refinement: `.env` holds secrets + is gitignored, so the generator owns a separate secret-free file), `litellm/config.yaml` (base + derived `model_list`, api_base `http://192.168.0.144:<port>`), and `models.download.tsv`. `--check` mode renders + diffs, non-zero on drift.
- [x] 2.4 Zero-diff cutover: regenerated `litellm/config.yaml` is **semantically identical** to the original (14 deployments, rate limits, aliases, all settings verified equal — only formatting/comments differ). `models.generated.env` matches the live `.env` except the **vestigial `GPU_7`** (no service consumes it — intended drop). Generated files committed.
- [x] 2.5 Schema validation in the generator: `kind` in allowed set, GPU index 1-8, no port collisions, unique `api_name`, chat deployments resolve to a gguf source (+ require `model_type`).
- [x] 2.6 Add `model-manifest-validate` CI job: `render-config.py --check` (schema-validate then drift-check; fails the build). Negative-tested: a hand-edit to `config.yaml` fails the gate with a diff. `litellm-validate` retained for `config-local.yaml` (hand-maintained).
- [x] 2.7 Rewired `scripts/download-models.sh` to consume `models.download.tsv` (single source), preserving `--fallback-q4` and adding `--dry-run`. **Surfaced a real gap:** the text-embed GGUF (`nomic-ai/nomic-embed-text-v1.5-GGUF`) was missing from the old script — now included (URL HEAD-verified 200).

## 3. CD — self-hosted deploy workflow (opt-in)

- [ ] 3.1 Register one self-hosted runner on Prod (`192.168.0.152`), label `homelab`; confirm it can SSH to PEA (`192.168.0.144`) over the LAN. _(USER INFRA — needs access to the Prod box; documented in `docs/pea-server-setup.md`.)_
- [ ] 3.2 Create the `production` GitHub Environment with required reviewer(s); add repo variables `DEPLOY_DIR`/`LITELLM_HEALTH_URL` and secrets `GPU_SERVER_HOST/USER/SSH_KEY`. _(USER INFRA — GitHub repo settings.)_
- [x] 3.3 Added `.github/workflows/deploy.yml` on `runs-on: [self-hosted, homelab]`, `workflow_dispatch` with a `target` input (`litellm` | `gpu-server` | `both`); manual-only trigger so fork PRs can never run it, `production` environment gate.
- [x] 3.4 LiteLLM deploy job: validates (`render-config.py --check` + `validate_config.py`), then on Prod `git checkout <sha>` → `docker compose up -d litellm` → polls `LITELLM_HEALTH_URL` (fails if unhealthy within timeout).
- [x] 3.5 GPU server deploy job: SSHes to PEA (`appleboy/ssh-action`), regenerates `models.generated.env`, native rebuild of `local-ai-llama:latest`, one-at-a-time `gpu-server-1..6` restart with `/health` check on ports 8080-8085; fail-fast.

## 4. Docs & validation

- [x] 4.1 Added a CI/CD section to `CLAUDE.md`: what CI validates, the `models.yaml` → generator workflow (edit manifest, never the generated files), deploy via `deploy.yml`, and manual fallback commands.
- [x] 4.2 Added self-hosted runner registration + deploy usage to `docs/pea-server-setup.md`; updated "Different Models" to the manifest flow; documented the manual `docker compose` fallback for Prod and PEA.
- [x] 4.3 `openspec validate fix-cicd-pipeline --strict` — passes.
