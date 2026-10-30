# Pin every floating container image and refresh pins on a schedule

## Why

Five production images on PEA and Prod float: `localai/localai:latest-gpu-nvidia-cuda-12` (the only image replica), `prom/prometheus:latest`, `prom/node-exporter:latest`, `grafana/grafana:11.6.2` (tag, no digest) and `postgres:16-alpine` (the LiteLLM key store). A reboot or `docker compose pull` can silently move any of them to a build nobody tested, and the LocalAI one would take the image route down without a code change. LiteLLM, speaches, Kokoro, Caddy and blackbox-exporter are already digest-pinned, so the pattern and the reasoning (the LiteLLM comment explains why its digest is load-bearing) exist; the remaining images just never got it. Pins also rot: nothing refreshes them, so the digest-pinned images and `requirements-test.txt` age until someone notices.

## What Changes

- **Digest-pin every image** in `gpu-server/docker-compose.yml`, `litellm/docker-compose.yml` and `langfuse/docker-compose.yml` to the digest currently running on the host (not the newest upstream), so the pin is a no-op deploy.
- **CI rejects unpinned images.** `compose-validate` gains a check that every `image:` in a deployed stack carries an `@sha256:` digest, with an allowlist for locally built images (`local-ai-*`).
- **Scheduled pin refresh.** Dependabot (or Renovate) opens PRs for docker digests, GitHub Actions and `gpu-server/requirements-test.txt` on a monthly cadence, grouped per stack, so refreshing a pin is a reviewed PR with CI, not a surprise on the host.
- Document in `CLAUDE.md` and `docs/pea-server-setup.md` that pins are bumped by PR and deployed by the rolling rollout, and which pins need extra qualification (LiteLLM: routing integration test and the least-busy patch; LocalAI: an image generation smoke test).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ci-validation`: adds requirements that deployed compose stacks use digest-pinned images and that dependency pins are refreshed by reviewed pull requests. ADDED delta only; existing requirements unchanged.

## Impact

- `gpu-server/docker-compose.yml`, `litellm/docker-compose.yml`, `langfuse/docker-compose.yml`, `.github/workflows/gpu-build.yml` (new check in `compose-validate`), `.github/dependabot.yml` (new), `gpu-server/tests/` (a test for the pin check), `CLAUDE.md`, `docs/pea-server-setup.md`.
- Live hosts: none if pinned to the running digests; `docker compose up -d --dry-run` must confirm no recreate before merging.
- The `test_litellm_least_busy_patch.py` test already pins the patch to the LiteLLM digest; a Dependabot bump of that image will fail CI until the patch is re-verified, which is the intended behaviour.
