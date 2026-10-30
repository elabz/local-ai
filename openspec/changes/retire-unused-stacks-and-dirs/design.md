## Context

Findings from the 2026-09-25 survey: `git ls-files gpu-image-server manuals-parser private` returns nothing; `private/` is gitignored on purpose (host-private custom-voice data); `gpu-image-server/` and `manuals-parser/` exist locally as empty or `__pycache__`-only directories with no ignore rule; `.gitignore` line 10 ignores `gpu-image-server/models/*.safetensors` for a directory with no tracked content. `langfuse/docker-compose.yml` defines langfuse, worker, postgres, clickhouse, redis, minio and an mc init job; `README.md` lists it as deployed on Prod at port 3002; `litellm/config.base.yaml` has callbacks `speech_correlation` and `prometheus` only, with Langfuse mentioned as an optional env comment.

## Goals / Non-Goals

**Goals:**
- Every top-level directory is tracked, ignored or gone; every ignore rule has a reason.
- Langfuse is either a working, documented observability path or absent.
- A CI check that keeps it that way.

**Non-Goals:**
- Auditing the contents of `private/` (deliberately host-private) beyond confirming its ignore rule.
- Choosing a different observability tool. If Langfuse is not used, the answer is "none for now", and LiteLLM's Prometheus metrics stay the observability surface.
- Any change to the deployed inference or proxy behaviour.

## Decisions

**D1. Langfuse decision is evidence-driven, default remove.** Task 1.1 checks Prod (`docker ps`) and asks the owner whether anyone opens the Langfuse UI. Unless it is running and used, remove: seven floating images and three databases for a tool no callback feeds is pure surface area. If kept, wiring it is one callback line plus documented keys and it enters the pinning change.

**D2. Orphan check is a script over `git ls-files`, `git check-ignore` and the README table.** For each top-level entry in the working tree (CI checks out a clean tree, so the check there covers tracked and documented entries; a `--local` mode run by hand covers this checkout's untracked directories). For ignore rules: every non-comment `.gitignore` line must match at least one path in `git log --all --name-only` or be annotated with a `# local-only:` comment explaining why it matches nothing tracked. Unit-tested with a temp git repo.

**D3. Local-only directories get an ignore rule with a comment, not deletion by the repo.** `manuals-parser/` and `gpu-image-server/` on this machine may be someone's scratch; the change deletes them locally only after the owner confirms (task 2.2), and either way adds annotated ignore rules so they can never be committed by accident.

## Risks / Trade-offs

- [Langfuse volumes hold traces someone wants] → `down` without `-v` first; volumes are removed only in a separate, confirmed step recorded in tasks.
- [The history-based ignore check is slow on a large repo] → 162 commits; it runs in well under a second. Revisit if it ever exceeds a few seconds.
- [README table drifts again] → the orphan check compares the table to the tree on every CI run.

## Migration Plan

1. Evidence and decision (section 1).
2. Repo edits, check, tests; CI green.
3. If removing Langfuse: on Prod, `docker compose -f langfuse/docker-compose.yml down` (keep volumes), confirm LiteLLM unaffected, then a confirmed `docker volume rm` of the Langfuse volumes.

Rollback: `git revert`; if Langfuse was brought down its volumes survive until the confirmed removal step.

## Open Questions

- Is Langfuse running on Prod, and does anyone use it? (1.1)
- Are `manuals-parser/` and `gpu-image-server/` on this machine wanted by the owner? (2.2)
