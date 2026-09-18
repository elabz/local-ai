## Why

PEA's host ran out of RAM twice on 2026-09-18, and the kernel killed `llama-server` both times (11:16 and 12:42; the second took out `pea-gpu-1` and `pea-gpu-2`). The cause is diagnosed in `evidence/2026-09-18-heartcode-handoff.md`: every chat worker runs llama.cpp build 8027 without `--cache-ram`, so each may grow an 8 GiB host-RAM prompt cache, and six of them can reach ~48 GiB on a 31 GB host. The container limits don't catch it because they add up to 42 GiB for chat alone. At 16:05Z the host had 3.2 GB available and 8 GB of swap in use (`evidence/2026-09-18-memory-snapshot.md`). HeartCode's pre-token retry has hidden the kills so far, but a kill after the first token surfaces as a mid-stream failure, and the August chat-quality runs were invalidated by this same failure class.

## What Changes

- Add a `CACHE_RAM` setting (MiB) to the chat wrapper and always pass `--cache-ram` to `llama-server`. llama.cpp's implicit 8 GiB default is never used again.
- Pick the per-worker cache bound by measurement: confirm that the growth is the prompt cache, and that repeated-prompt TTFT with `--cache-reuse` stays within 10% of today's value.
- Set every chat worker, including `gpu-server-6` (currently 2 GiB with no override), to one consistent `mem_limit` and `memswap_limit` derived from the cache bound.
- Right-size non-chat limits to measured peak plus margin, so that the sum of all PEA container limits fits in physical RAM minus an OS reserve.
- Add a CI check that fails when the PEA compose memory limits exceed that budget, or when a service has no limit.
- Rewrite the stale "Memory Budget" comment in `gpu-server/docker-compose.yml` (it still describes a 16 GB host), and correct the "~1.5 GiB per chat container" premise in the archived `restore-nsfw-chat-capacity` design.
- Roll out one worker at a time, then confirm no OOM kills under sustained load on both routes.

## Capabilities

### New Capabilities
- `host-memory-budget`: PEA container memory is bounded and adds up. Chat workers have an explicit host prompt-cache bound, every container has a limit, the limits fit in physical RAM, and CI enforces this.

### Modified Capabilities

## Impact

- **Code:** `gpu-server/config.py`, `gpu-server/server.py`, `gpu-server/docker-compose.yml`, a new `gpu-server/scripts/check-memory-budget.py`, `.github/workflows/gpu-build.yml`, and tests under `gpu-server/tests/`.
- **Production:** rolling restarts of `pea-gpu-1..6`, and recreates of the non-chat containers whose limits change. Each chat route keeps two of its three replicas serving during the roll. Restarting a worker empties its prompt cache, so its first turn per session is cold.
- **Unchanged:** the llama.cpp build stays at 8027 (pinned deliberately); `--ctx-size` stays at 16384 (that is `raise-context-window`'s decision); no LiteLLM change.
- **Related:** `prevent-load-induced-gpu-restarts` (archived; health-probe false positives, not memory) and `restore-nsfw-chat-capacity` (archived; its RAM premise was wrong). HeartCode should be told when this lands, so evaluations can record "PEA RAM bounded" as a precondition.
