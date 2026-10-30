# Retire unused stacks, dead ignore rules and stray directories

## Why

The repo carries things that look deployed but are not, which costs every reader a verification step (the `Verify CLAUDE.md topology` memory exists because of exactly this). Specifically: the `langfuse/` stack (seven services, floating images) is described in `README.md` as running on Prod, but LiteLLM's `callbacks` block does not reference it and nothing here proves it is up; `.gitignore` still carries a `gpu-image-server/models/*.safetensors` rule for a directory that has no tracked files; and the working tree on this machine holds empty or pycache-only `gpu-image-server/` and `manuals-parser/` directories that are neither tracked nor ignored, so `git status` on a fresh clone and on this checkout disagree. `project-health-improvements` cleared the larger clutter on 2026-09-18; these are the leftovers.

## What Changes

- **Decide Langfuse: wire it in or remove it.** Check Prod for running Langfuse containers. If it runs and anyone uses it, add the `langfuse` callback to `litellm/config.base.yaml`, document the keys, and let `pin-floating-container-images` pin it. If not, delete `langfuse/`, its README rows and the three `LANGFUSE_*` environment lines in `litellm/docker-compose.yml` and `config.base.yaml`.
- **Remove dead ignore rules** and add ignore rules for local-only directories that must not be committed, or delete those directories, so a fresh clone and this checkout show the same tree.
- **CI check for orphans.** `compose-validate` fails when a top-level directory is neither tracked, ignored, nor listed in the README's repository table, and when a `.gitignore` rule matches no path that ever existed in history. Cheap, and it stops this class of drift from returning.
- Update `README.md`'s component table and architecture diagram and `CLAUDE.md`'s repository structure to the result.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ci-validation`: adds a requirement that the repository's top-level layout, its ignore rules and its documented component table agree. ADDED delta only.

## Impact

- `langfuse/` (kept and wired, or removed), `litellm/config.base.yaml` and `litellm/docker-compose.yml` (Langfuse callback and env), `.gitignore`, `README.md`, `CLAUDE.md`, `.github/workflows/gpu-build.yml` (new check), a small script under `scripts/` or `gpu-server/scripts/` with a unit test.
- Live hosts: if Langfuse is removed, `docker compose down` of its stack on Prod (user-confirmed; its volumes hold traces only, and removing them is the destructive step that needs an explicit yes).
