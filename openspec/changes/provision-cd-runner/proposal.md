# Provision the self-hosted deploy runner, or retire the deploy workflow

## Why

`.github/workflows/deploy.yml` requires a self-hosted runner labelled `homelab` on Prod and a `production` Environment with required reviewers. Neither is confirmed to exist: every deploy in the last month (memory limits, Alertmanager, least-busy patch, GPU 5 removal) was done by hand over SSH, and `project-health-improvements` 5.6 left "CD runner and Environment setup" as an unopened follow-up. The archived `fix-cicd-pipeline` change dropped its cd-deploy delta at triage for the same reason. `CLAUDE.md` and `docs/pea-server-setup.md` describe `deploy.yml` as the primary path and the manual steps as a fallback, which is the reverse of reality. Either the runner gets registered and the workflow is proven with a real deploy, or the workflow and its docs go, so nobody follows a path that does not work.

## What Changes

- **Decide, then do one of two things.** Default: provision. Register the runner on Prod as a systemd service under a dedicated user, create the `production` Environment with the user as required reviewer, set the documented variables and secrets, and run `deploy.yml` for `litellm` then `gpu-server` as real deploys of an already-deployed commit (proven no-op).
- **If the owner declines the runner**, delete `deploy.yml`, rewrite the CD sections of `CLAUDE.md` and `docs/pea-server-setup.md` around the manual procedure and the `pea-rolling-rollout` skill, and archive this change with that decision recorded.
- **Make the workflow match the rollout skill.** The gpu-server job's rolling restart must gate each replica on `/health`, never restart two replicas of one route, keep GPU 5 out, and finish with a `--dry-run` no-op check, the same rules `pea-rolling-rollout` enforces by hand.
- **Runner health is visible.** A weekly scheduled no-op run (`target: litellm`, health-check only) fails loudly when the runner is offline, so a dead runner is found before it is needed.

## Capabilities

### New Capabilities

- `cd-deploy`: the deployment workflow's contract: where it runs, what it gates on, what it must never do, and how its runner's availability is verified.

### Modified Capabilities

_None._

## Impact

- `.github/workflows/deploy.yml` (rolling-restart rules, weekly probe, or deletion), GitHub repo settings (Environment, variables, secrets, runner registration: user-performed), Prod host (runner service under its own user, SSH key to PEA), `docs/pea-server-setup.md` CI/CD section, `CLAUDE.md` CI/CD section, `openspec/specs/ci-validation` cross-reference.
- Secret operations (runner token, SSH key, Environment secrets) need the user; the change provides the exact steps.
