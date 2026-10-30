## Context

`deploy.yml` is manual-only (`workflow_dispatch`), gated by the `production` Environment, and runs two jobs on `[self-hosted, homelab]`: LiteLLM (checkout SHA, `compose up -d litellm`, readiness check on Prod) and gpu-server (SSH to PEA, regenerate env, `docker build`, rolling `gpu-server-1..6` restart with `/health` gating). `docs/pea-server-setup.md` step "register the self-hosted runner" already has the runner install commands. There is no evidence in the repo or in memory that the runner was ever registered or the Environment created; all recorded deploys are manual.

Since the workflow was written, the deploy rules have tightened: GPU 5 is quarantined from the chat route; the controller recreates whole slots; `--cache-ram` and memory limits are mandatory; the `pea-rolling-rollout` skill codifies one-replica-at-a-time with a final no-op proof. `deploy.yml` predates most of that.

## Goals / Non-Goals

**Goals:**
- The documented deploy path is the one that actually works.
- If automated: a real, reviewed, health-gated deploy that follows the same rules as the manual procedure, and a runner whose absence is noticed.
- If not: no dead workflow and no docs pointing at it.

**Non-Goals:**
- Continuous deployment on push. Deploys stay manual and reviewed.
- Deploying the image, speech, or monitoring services from the workflow. Those remain manual (they are rare and each has host-specific steps).
- Replacing the failure controller or the rolling-rollout skill.

## Decisions

**D1. Provision by default; the owner can veto.** The runner costs nothing on Prod (no GPU, small CPU), and an audited, reviewed deploy with a recorded SHA is worth more than the manual steps' flexibility once the workflow follows the same rules. The decision is task 1.1 and is recorded in this file either way.

**D2. Runner runs as its own user, as a systemd service, with a Prod-local SSH key to PEA scoped to the deploy user there.** `config.sh` then `svc.sh install` from the GitHub instructions in `docs/pea-server-setup.md`. The Docker socket access it needs on Prod is group membership, not root. Ephemeral runners were considered and rejected: one long-lived runner on a private host is simpler and the repo is private.

**D3. Rolling restart in the workflow mirrors `pea-rolling-rollout`.** Order SFW 1, NSFW 4, SFW 2, NSFW 6, SFW 3 (so two replicas of one route are never down together), skip any service listed as quarantined in `models.yaml`, wait for `/health` 200 with a bounded timeout, abort on the first failure leaving the remaining replicas untouched, and end with `docker compose up -d --dry-run` asserting no change. The restart list is derived from the manifest, not hardcoded, so the GPU 5 removal and future tenancy edits carry through.

**D4. Weekly probe run.** A `schedule:` trigger every Monday runs only the LiteLLM health check step (a new `target: probe`), which fails when the runner is offline (GitHub marks the job queued, then failed after the timeout). A failed scheduled run emails the repo owner; nothing else to build.

**D5. Proof is a no-op deploy of the live commit.** The first real run of each target deploys the SHA already running; success means the workflow's steps agree with the hosts. Only after that does the next real change go through it.

## Risks / Trade-offs

- [Runner offline when a deploy is urgent] → manual procedure stays documented as the fallback; the weekly probe keeps offline periods short.
- [Workflow restarts a chat replica while the controller is mid-recovery] → the workflow checks the controller's inventory (`gpu-topology.json`) and refuses to touch a slot marked recovering; the same check the rollout skill makes by hand.
- [Environment reviewer is the same person who dispatches] → GitHub allows self-approval only if configured; leave "prevent self-review" off since there is one operator, but record it.
- [Runner token or SSH key in the wrong place] → both are entered by the user through the GitHub UI and the Prod shell; the repo never sees them.

## Migration Plan

1. Decision (1.1). If declined, jump to the retirement tasks and archive.
2. Update `deploy.yml` (D3, D4); CI's `compose-validate` and `actionlint` (if added) green.
3. User registers the runner, creates the Environment, sets variables and secrets from the ready-made steps.
4. Dispatch `litellm` with the live SHA; then `gpu-server` with the live SHA; both must be no-ops on the hosts.
5. Docs: CD section rewritten to "deploy.yml first, manual fallback", with the probe and its failure meaning.

Rollback: remove the runner service; the manual procedure is unaffected.

## Open Questions

- Does the owner want the runner at all? (1.1)
- Is `actionlint` worth adding to CI for this and `gpu-build.yml`? Cheap; decide during 2.x.
