## Context

`.github/workflows/gpu-build.yml` is the repo's only workflow and has failed on every run. The failure mode (confirmed from run logs):

- Build of `gpu-server/Dockerfile` (llama.cpp + CUDA for Pascal) **succeeds** in ~13 min.
- Push to `ghcr.io/elabz/local-ai/gpu-server` **fails**: `denied: installation not allowed to Create organization package` — the workflow declares no `permissions:`, so `GITHUB_TOKEN` lacks `packages: write`.
- The `Deploy to GPU servers` step never runs, and could never succeed: it `appleboy/ssh-action`s to `192.168.0.144`, a **private LAN address GitHub-hosted runners cannot route to**.

Two structural mismatches make the current design unsalvageable as-is:

1. **Deployment is build-on-host, not registry-pull.** `gpu-server/docker-compose.yml` runs `image: local-ai-llama:latest` (built on PEA via `docker build`), plus `local-ai-vision-embed:latest` and `local-ai-dino-embed:latest`. The GHCR image the workflow pushes/pulls is never referenced by compose.
2. **Targets live on a private LAN.** PEA (`192.168.0.144`) and Prod (`192.168.0.152`) are only reachable from inside the network. A cloud runner cannot deploy to them.

Constraints from the hardware/topology (see `CLAUDE.md`, `[[pea-p104-ml-constraints]]`): PEA is a no-AVX Celeron with 8× Pascal P104-100; the llama.cpp image needs the no-AVX/`compute 6.1` build flags and is best built natively on PEA. Prod has no GPU and spare CPU.

A second, related pain motivates this change: **changing a model or its tenancy is error-prone.** Chat servers already parameterize the model (`MODEL_PATH: ${GPU_1_MODEL_PATH:-...}`, `MODEL_TYPE`, `MODEL_NAME` in `docker-compose.yml`), but embed/image servers bake the model into the `command:` block, the GGUF download list lives in `scripts/download-models.sh`, and routing lives in `litellm/config.yaml`. A single swap touches 2-3 files that must be kept in sync by hand, with duplicated ports/IPs/GPU indices. There is no single source of truth for "which model runs where, and how is it routed."

## Goals / Non-Goals

**Goals:**
- Stop the failing-workflow emails — CI must pass on GitHub-hosted runners.
- Make CI *useful*: catch real regressions in compose files, LiteLLM config, and the Python services before they reach the hosts.
- Provide a working, opt-in path to deploy **LiteLLM config to Prod** (the user's stated future need) and rebuild/restart **GPU servers on PEA**, from CI.
- Make **changing a model or its tenancy a one-file edit** (`gpu-server/models.yaml`) with CI-enforced consistency across the chat `.env`, LiteLLM routing, and the download list.
- Least-privilege, minimal-churn changes; no application code edits.

**Non-Goals:**
- Switching the deployment model to registry-pull (GHCR-based). Out of scope; build-on-host stays.
- Auto-deploying GPU server images on every merge (heavy build, GPU contention) — deploys stay manual/opt-in.
- Running model inference or GPU tests in CI (no GPU on runners).
- Pinning llama.cpp to a release (tracked as an open question, not done here).
- **Generating the full `docker-compose.yml`** from the manifest. The manifest owns *model + routing*, not service *topology* — structural changes (turning a chat GPU into an embed GPU: different image/`command`/healthcheck) stay manual compose edits. Over-generating compose's healthchecks, GPU UUIDs, and `deploy.resources` blocks is high-risk for low gain.

## Decisions

### Decision 1 — Validation-first CI, not build-push-deploy
Replace the single job with parallel **validation** jobs that run on `ubuntu-latest` and gate merges:
- `compose-validate`: `docker compose -f <stack>/docker-compose.yml config -q` for `gpu-server`, `litellm`, `monitoring`, `langfuse`.
- `litellm-validate`: parse `litellm/config.yaml` (+ `config-local.yaml`); assert unique `model_name`s, every `litellm_params` has an `api_base`, and `model_list` is non-empty. A small Python check script under `litellm/` or inline.
- `python-lint`: `ruff check` + `python -m py_compile` over `gpu-server/*.py`, `gpu-server/vision-embed/*.py`, `gpu-server/dino-embed/*.py`.

*Why:* From the cloud, the highest-value thing CI can do is fast feedback on the artifacts that actually break deploys (YAML typos, bad routes, Python syntax). It runs in seconds, always passes when the repo is healthy, and needs no secrets or LAN access. *Alternative considered:* keep build-push-deploy and just add `packages: write` — rejected: the deploy half still can't reach the LAN and the pushed image is unused, so it would be green-but-pointless.

### Decision 2 — Build the gpu-server image as a build-only check (no push)
Keep a `gpu-build` job that runs `docker/build-push-action` with `push: false`, path-filtered to changes in `gpu-server/Dockerfile`, `gpu-server/requirements.txt`, or the wrapper `*.py`. Use `cache-from/to: gha` to keep it fast.

*Why:* The llama.cpp image builds from `main` and can break on upstream changes; a build-only check catches that before it reaches PEA, without needing GHCR permissions or being tied to the (unused) registry flow. *Alternative considered:* push to GHCR with `packages: write` and switch compose to pull — rejected (registry auth on PEA, native no-AVX build is simplest on-host, larger blast radius). Reintroducible later if the model changes.

### Decision 3 — CD runs on a self-hosted runner on the LAN
Add `deploy.yml` with `runs-on: [self-hosted, homelab]`. Register **one** self-hosted runner on **Prod (`192.168.0.152`)** — it has no GPU contention and can SSH to PEA over the LAN. The deploy job then reaches both hosts: LiteLLM locally on Prod, GPU servers via LAN SSH to PEA (reuse `appleboy/ssh-action`, now from inside the network).

*Why:* A self-hosted runner is the only mechanism that can route to `192.168.0.x`. One runner + LAN-internal SSH covers both hosts with minimal infra. *Alternatives considered:* (a) Tailscale/WireGuard from a cloud runner — works, but adds a tunnel + auth-key secret and keeps builds off-host; deferred. (b) Pull-based (watchtower / cron `git pull`) — rejected: no gating, no manual control, no health-gated rollout.

### Decision 4 — Deploy triggers are explicit and gated
`deploy.yml` triggers on `workflow_dispatch` with an input choosing target (`litellm` | `gpu-server` | `both`). Optionally a `push` trigger on `litellm/**` to main for hands-off config rollout — but default to manual-first. Guard self-hosted jobs so they never run on fork PRs (`if: github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/main'`), and use a GitHub **Environment** (`production`) with required reviewers for an approval gate.

*Why:* Self-hosted runners execute arbitrary workflow code; gating to dispatch/main + environments prevents untrusted PRs from running on the LAN host and adds a human checkpoint for production.

### Decision 5 — LiteLLM deploy = validate → pull → restart → health-check
The LiteLLM config is plain YAML in the repo. Deploy = on Prod, `git pull` (or copy the validated `config.yaml`), `docker compose up -d litellm`, then poll `/health` and the LiteLLM `/health/readiness`. Run the Decision-1 `litellm-validate` check as a prerequisite of the deploy job so a bad config can't be rolled out.

*Why:* Smallest reliable mechanism for a config-only service; reuses existing `docker compose` flow from `CLAUDE.md`. GPU server deploy mirrors the old script's one-at-a-time restart with health checks, but only after a native rebuild on PEA.

### Decision 6 — Modernize actions, declare per-job permissions
Bump `actions/checkout` and `docker/*` actions to Node 24-compatible versions (silences the deprecation annotation). Each job declares least-privilege `permissions` (validation jobs: `contents: read`).

### Decision 7 — Single manifest as source of truth; generator renders the rest
Introduce `gpu-server/models.yaml`: a list of served models, each with `api_name` (+ `aliases`), `kind` (`chat` | `text-embed` | `vision-embed` | `visual-embed` | `image`), `deployments` (slot/GPU index + port for each backend instance), `source` (GGUF filename or HF repo for the downloader), and routing knobs (`rpm`, etc.). A generator `gpu-server/scripts/render-config.py` reads it and renders three artifacts:

1. **`gpu-server/models.generated.env`** — the `GPU_N_MODEL_PATH/TYPE/NAME` values the chat services consume (compose.yml:116-118), so chat model swaps need no compose edit. (Refinement during apply: the existing `gpu-server/.env` is gitignored and holds **secrets** (`LITELLM_MASTER_KEY`, Langfuse keys), so the generator owns a **separate secret-free file**, committed + drift-checked; secrets stay in the hand-maintained `.env`. Deploy loads both: `docker compose --env-file .env --env-file models.generated.env up -d`.)
2. **`litellm/config.yaml`** — by merging hand-maintained `litellm/config.base.yaml` (router_settings, general_settings, litellm_settings) with a manifest-derived `model_list` (api_base per backend `http://192.168.0.144:<port>`, aliases, rate limits).
3. **The download list** consumed by `scripts/download-models.sh` (GGUF filenames / HF repos).

*Why split, not full-generation:* the parameterized chat env and routing are repetitive and sync-prone — ideal to generate. Compose *structure* (per-kind images, `command:` blocks, GPU UUIDs, `deploy.resources`) is not, so it stays hand-maintained (see Non-Goals). Merging a `config.base.yaml` keeps router/rate-limit knobs hand-editable while models come from the manifest. *Alternative considered:* a thin "edit `.env` + checklist" approach with no generator — rejected (user chose manifest+generator); it leaves the download list and LiteLLM routing as separate manual steps, which is exactly the drift we're removing.

### Decision 8 — CI enforces manifest↔generated-file consistency
Generated files (`gpu-server/models.generated.env`, `litellm/config.yaml`, `models.download.tsv`) are **committed**. A `model-manifest-validate` CI job: (a) schema-validates `models.yaml` (kind in the allowed set, GPU index 1-8, no port collisions, every chat deployment resolves to a model source, `api_name`s unique), then (b) re-renders and compares against the committed files — **drift fails the build**. (`gpu-server/.env` itself stays gitignored/hand-maintained for secrets and is not drift-checked.)

*Why commit generated files + check drift:* keeps the repo's deployable state reviewable in PRs (you see the resulting env/routing diff), works with the build-on-host/`git pull` deploy model, and makes "someone hand-edited `config.yaml` instead of the manifest" a loud CI failure rather than silent drift.

## Risks / Trade-offs

- **Self-hosted runner runs workflow code on a LAN host** → Restrict deploy jobs to `workflow_dispatch`/`main`, never fork PRs; use a `production` Environment with required reviewers; keep the runner's OS account least-privileged. Validation CI stays on GitHub-hosted runners (untrusted PRs never touch the runner).
- **Runner is a new always-on dependency on Prod** → It only needs to be up for deploys; if down, fall back to the documented manual `docker compose` commands (current process). No regression vs today.
- **llama.cpp builds from `main` can break unpredictably** → Build-only CI surfaces it before PEA; pinning to a release is an open question below.
- **Removing GPU deploy automation until the runner is set up** → Acceptable: it never worked anyway, and GPU deploys are already manual on PEA.
- **`docker compose config` needs the referenced images/env to validate** → Use `config -q` (parse/interpolate only, no pull/build); provide a CI `.env`/defaults if interpolation requires vars.
- **Generated files can drift if hand-edited** → CI's regenerate-and-diff (Decision 8) fails loudly on any manual edit; docs make clear `models.yaml` is the only file to touch for model/tenancy changes.
- **Manifest can't express a structural retopology** (e.g. chat GPU → embed GPU) → Documented as a manual compose edit (Non-Goal); the manifest validates against the *current* topology so it can't silently point a chat slot at a GPU that isn't running a chat service.
- **Generator becomes a new dependency for deploys** → Keep it a single dependency-light `render-config.py` (stdlib + `PyYAML`); commit its output so a deploy can also just `git pull` the already-rendered files without running the generator on the host.

## Migration Plan

1. **Land the workflow rewrite** (validation jobs + build-only `gpu-build`, modern actions, per-job permissions). This alone stops the failure emails on the next `gpu-server/**` push. Fully reversible by reverting the file.
2. **Register the self-hosted runner** on Prod (`./config.sh` with repo URL + token; label `homelab`); add/move secrets (`PROD_HOST/USER/SSH_KEY`, `GPU_SERVER_HOST/USER/SSH_KEY`) and create the `production` Environment.
3. **Add `deploy.yml`**; test `workflow_dispatch` → `litellm` on a no-op config change end-to-end; then GPU-server path.
4. **Introduce the manifest as a zero-diff cutover:** write `models.yaml` + `render-config.py` so regenerating reproduces today's committed `gpu-server/.env`, `litellm/config.yaml`, and download list **byte-for-byte** (or with only intended diffs), commit the generated files, then wire the `model-manifest-validate` CI job. From then on, model/tenancy changes are `models.yaml` edits flowing through CI → `deploy.yml`.
4. **Document** in `CLAUDE.md` (CI/CD section) and `docs/pea-server-setup.md` (runner registration + deploy usage).

**Rollback:** Revert the workflow file(s); deploys revert to the manual `docker compose` commands already in `CLAUDE.md`. No data or service state is affected.

## Open Questions

- Pin llama.cpp to a tagged release in the Dockerfile (reproducible builds) vs. track `main` (current)? Recommend pinning in a follow-up.
- Auto-deploy LiteLLM on `litellm/**` push to main, or keep deploys strictly `workflow_dispatch`? Recommend manual-first, revisit after a few cycles.
- Place the self-hosted runner on Prod (recommended) or PEA? Prod avoids GPU contention but means LAN SSH to PEA for GPU deploys.
- Should the manifest also drive per-GPU tuning (`N_CTX`, `N_GPU_LAYERS`, KV-cache quant) currently in `x-gpu-env-common`, or keep those as compose-level defaults? Start with model + routing only; expand if needed.
- Migration ordering: land the CI/deploy fix (Phase 1) first, then introduce the manifest as a follow-on slice within this change so the generated `config.yaml`/`.env` exactly reproduce today's committed files (zero-diff cutover) before anyone relies on editing the manifest.
