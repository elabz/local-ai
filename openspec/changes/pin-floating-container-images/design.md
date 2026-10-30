## Context

Pinned today (digest): LiteLLM, speaches, kokoro-fastapi, caddy, blackbox-exporter. Floating: LocalAI (`latest-gpu-nvidia-cuda-12`), Prometheus (`latest`), node-exporter (`latest`), Grafana (`11.6.2` tag only), Postgres (`16-alpine`, in both litellm and langfuse stacks), and all of the Langfuse stack (`langfuse:3`, `clickhouse:24`, `redis:7-alpine`, `minio:latest`, `mc:latest`). Locally built images (`local-ai-llama`, `local-ai-vision-embed`, `local-ai-dino-embed`, `local-ai-speech-observability`) are built on PEA and cannot carry a registry digest.

Nothing refreshes pins. `requirements-test.txt` is pinned to what `pea-gpu-1` ran on 2026-09-18. Actions are pinned by major tag.

## Goals / Non-Goals

**Goals:**
- No registry image in a deployed stack without a digest.
- The pin change itself is a no-op on the hosts.
- A monthly, grouped, CI-gated path to bump pins.

**Non-Goals:**
- Upgrading anything. Every pin is to the digest already running.
- Pinning locally built images (they are versioned by the git SHA that built them; a later change could add `image: local-ai-llama:<sha>` but that is deploy tooling, not this change).
- Deciding whether Langfuse stays; `retire-unused-stacks-and-dirs` decides that. Its stack is pinned anyway because pinning is a no-op and the check is stack-wide.

## Decisions

**D1. Pin to the running digest, read from the host.** `docker inspect --format '{{index .RepoDigests 0}}'` on PEA and Prod for each floating image, not `docker pull` of the tag. Alternative: pin to the newest upstream digest. Rejected: it would be an upgrade of the only image replica and of the key store's Postgres in a change whose purpose is to stop surprises.

**D2. CI check is a small script, not a regex in YAML.** `gpu-server/scripts/check-image-pins.py` parses `docker compose config --format json` output for each stack and requires `@sha256:` on every image not matching `^local-ai-`. A unit test covers pass, fail and the allowlist. Runs in the existing `compose-validate` job, which already renders every stack.

**D3. Dependabot over Renovate.** Dependabot is built into GitHub, needs no app install, and supports the three ecosystems needed: `docker` (per compose directory), `github-actions`, `pip` (`gpu-server/requirements-test.txt`). Monthly, grouped per directory so a stack's bumps land in one PR. Renovate would allow digest-only updates of a pinned tag more precisely, but the extra app is not worth it for three ecosystems.

**D4. Qualification is recorded next to the pin.** Each image whose bump needs more than green CI gets a comment on its `image:` line saying what to run (LiteLLM already has this; LocalAI needs an image-generation smoke test; Postgres major bumps need a dump/restore, which `backup-litellm-postgres` provides). Dependabot PRs for those images are labelled `needs-qualification` via the config's `labels` field.

## Risks / Trade-offs

- [Dependabot `docker` ecosystem may propose tag bumps as well as digest bumps] → configure `ignore` for major versions on Postgres and Grafana; review remains manual.
- [Digest on Prod differs from the digest on PEA for the same tag (Postgres)] → pin each stack to its own host's digest; they are different stacks.
- [A pin comment goes stale] → the comment names the test to run, not a result; results live in the PR that bumps it.

## Migration Plan

1. Collect digests from both hosts (read-only `docker inspect`), pin, add the check and Dependabot config, CI green.
2. On each host, `docker compose up -d --dry-run` must show no recreate; then `up -d` (no-op) and record it.
3. First Dependabot run: triage the PRs, merge only what CI and the recorded qualification allow.

Rollback: `git revert` of the pin commit; the hosts keep running the same digests either way.

## Open Questions

- Is Langfuse running on Prod at all? If not, pin it anyway (harmless) and let `retire-unused-stacks-and-dirs` decide its fate.
- Should Grafana's `11.6.2` be treated as pinned (immutable version tag) or given a digest? Decision: digest, so one rule covers every image.
