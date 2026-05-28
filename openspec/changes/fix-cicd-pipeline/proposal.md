## Why

The `GPU Server Build` workflow (`.github/workflows/gpu-build.yml`) has failed on **every run** — it just became noisy now that recent `gpu-server/**` PRs (vision-embed, DINOv2) keep triggering it. Two root causes, both fatal:

1. **Push is denied.** The job builds the llama.cpp image (~13 min) then fails at push: `denied: installation not allowed to Create organization package`. The workflow never declares `permissions: packages: write`, so the `GITHUB_TOKEN` can't create/write the GHCR package.
2. **The deploy step can never run.** It SSHes to `192.168.0.144` (PEA) — a **private LAN IP unreachable from GitHub-hosted runners** — and even if it connected, it `docker pull`s the GHCR image while `gpu-server/docker-compose.yml` actually runs a **locally-built** `image: local-ai-llama:latest`. The pulled image is never used.

The pipeline is fundamentally misaligned with how this homelab deploys (build-on-host over a private LAN). Beyond just stopping the failures, the user wants CI/CD to become *useful* — specifically to push LiteLLM config (and other) updates to production safely.

## What Changes

- **BREAKING (remove the broken job):** Replace the single build-push-deploy job in `gpu-build.yml` with cloud-safe **validation** + a **build-only** image job (no push, no LAN SSH). The GHCR push and `appleboy/ssh-action` deploy steps are removed — they never worked from a cloud runner.
- **Add `permissions:` and path filters.** Declare least-privilege `permissions` per job. Path-filter so Python-only embed changes (`vision-embed/`, `dino-embed/`) don't trigger the expensive llama.cpp CUDA build, which only depends on `Dockerfile` + `requirements.txt` + the wrapper `.py`.
- **Add validation CI** that actually catches regressions and passes on GitHub-hosted runners:
  - `docker compose config` for all stacks (`gpu-server`, `litellm`, `monitoring`, `langfuse`).
  - LiteLLM `config.yaml` validation (YAML parse + structural sanity: unique `model_name`s, every deployment has `api_base`, no dangling routes).
  - Python lint + byte-compile (`ruff` + `py_compile`) for the three FastAPI services (`gpu-server/`, `vision-embed/`, `dino-embed/`).
- **Add an opt-in deploy workflow (`deploy.yml`)** that runs on a **self-hosted runner on the LAN** (the only way CI can reach PEA/Prod). Triggered by `workflow_dispatch` (and optionally push to `litellm/**`), it deploys LiteLLM config to Prod (`192.168.0.152`: git pull + `docker compose up -d litellm`) and can rebuild/restart GPU servers on PEA (`192.168.0.144`). Requires the user to register one self-hosted runner (documented infra step).
- **Modernize actions** to silence the Node 20 deprecation warnings (`checkout@v4`→current, `docker/*` actions to Node 24-compatible versions).
- **Add a single model/tenancy manifest + generator.** Today a model swap touches 2-3 hand-edited, must-stay-in-sync places (chat `.env` vars, embed `command:` blocks, `scripts/download-models.sh`, `litellm/config.yaml`). Introduce `gpu-server/models.yaml` as the source of truth (per served model: API name + aliases, kind, GPU slot(s)/port(s), model source, rate limit) and a generator (`gpu-server/scripts/render-config.py`) that renders the `gpu-server/.env`, the LiteLLM `model_list`, and the download list from it. CI fails on drift (regenerate → `git diff` must be empty); the `deploy.yml` regenerates + applies. Edit one file → PR → rollout.

## Capabilities

### New Capabilities
- `ci-validation`: On every push/PR, run validation that passes on GitHub-hosted runners and blocks merges on real breakage — compose config for all stacks, LiteLLM config sanity, Python lint/compile, and a path-filtered build-only check of the gpu-server image.
- `cd-deploy`: A self-hosted-runner deploy workflow that pushes config/image updates to LAN hosts — LiteLLM config to Prod and GPU server rebuild/restart to PEA — triggered manually (and optionally on `litellm/**` changes).
- `model-manifest`: A single `gpu-server/models.yaml` source of truth for which model runs on which GPU/port and how it's routed, plus a generator that renders the chat `.env`, the LiteLLM `model_list`, and the download list — so changing a model or its tenancy is a one-file edit, with CI enforcing that generated files stay in sync.

### Modified Capabilities
<!-- None. gpu-rebalance is unaffected; this change only touches .github/workflows and docs. -->

## Impact

- **`.github/workflows/gpu-build.yml`** rewritten (validation + build-only); **new `.github/workflows/deploy.yml`** (self-hosted, opt-in).
- **No application code changes.** Compose files, LiteLLM `config.yaml`, and Python services are unchanged — only validated.
- **Infra prerequisite for CD:** one self-hosted GitHub Actions runner registered on the LAN (recommended on Prod `192.168.0.152`, which has no GPU contention and can SSH to PEA over the LAN). Repo secrets for the existing `appleboy/ssh-action` (`GPU_SERVER_HOST/USER/SSH_KEY`, plus `PROD_*` equivalents) move from the cloud job to the self-hosted deploy job.
- **GHCR is dropped** as part of the flow (compose builds on-host); can be reintroduced later if the deployment model switches to registry-pull.
- **New files for the manifest:** `gpu-server/models.yaml` (source of truth), `gpu-server/scripts/render-config.py` (generator), `litellm/config.base.yaml` (hand-maintained router/general settings the generator merges). `litellm/config.yaml`, `gpu-server/models.generated.env`, and `gpu-server/models.download.tsv` become **generated, committed** artifacts (no longer hand-edited). The gitignored, secret-bearing `gpu-server/.env` stays hand-maintained. Structural moves (changing a GPU's *service kind* — e.g. chat→embed) remain manual compose edits; the manifest owns model + routing, not service topology.
- **Docs:** `CLAUDE.md` (add a CI/CD section + manifest workflow) and `docs/pea-server-setup.md` (self-hosted runner registration + deploy usage).
