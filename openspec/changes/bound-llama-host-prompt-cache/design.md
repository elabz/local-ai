## Context

- PEA: 32,023 MiB RAM, 16 GiB swap, 2-core Celeron. Six chat workers (`pea-gpu-1..6`), each a FastAPI wrapper (`server.py`) around `llama-server` build 8027 (pinned), `--parallel 1`, `--ctx-size 16384`, q8_0 KV, `--cache-reuse 256`, no `--cache-ram`.
- llama.cpp's host prompt cache (PR 16391) keeps KV state of prompts evicted from the slot in host RAM so that a returning conversation can be restored instead of re-ingested. On build 8027 it defaults to **8,192 MiB per server**. With one slot per worker, every switch between two conversations evicts one of them to this cache, so it fills in proportion to the number of distinct sessions a worker serves.
- Measured state and OOM history are in `evidence/`. Busy workers sit at 7.5–8.5 GiB. The chat limits add up to 42 GiB and every container's limit to about 65 GiB, on a 31 GB host. Seven containers have no limit at all.
- Operational constraints (from the handoff): the GPU failure controller re-runs `docker compose up -d` for stopped services, so changes go through compose, never through `docker stop` or a hand-run `docker run`. An OOM mid-request can wedge the wrapper's `/health` at 503 `inference_active`. Each route must keep serving during rollout.

## Goals / Non-Goals

**Goals:**
- No host OOM kills of `llama-server` under sustained load on both routes.
- Every PEA container has a memory limit, and the limits add up to less than physical RAM minus an OS reserve. CI enforces this.
- Prompt-cache reuse keeps paying: repeated-prompt TTFT within 10% of today's value.

**Non-Goals:**
- Changing the llama.cpp build, `--ctx-size`, `--parallel` or the models.
- Shrinking the context window. That belongs to `raise-context-window`, even though it would also shrink cache entries.
- Solving swap use in general. Swap stays available as a small per-container cushion, not a budget line.

## Decisions

### D1. Always pass `--cache-ram` from a setting

Add `cache_ram: int` (MiB, env `CACHE_RAM`) to `config.py` and append `--cache-ram` next to `--cache-reuse` in `server.py`. Set it once in the `x-gpu-env-common` environment anchor, so all six workers share it and one worker can be overridden for the qualification run. The code default is 8192, llama.cpp's own implicit default made explicit, so deploying the code is behavior-neutral and every change in bound goes through compose. **Never `0`**: `--cache-reuse` is documented as depending on prompt caching, and HeartCode relies on it. **Never `-1`** (unlimited).

*Alternative rejected:* `EXTRA_ARGS: "--cache-ram N"`. It works, but it hides a memory-critical knob in a free-form string that neither CI nor tests can see.

### D2. The chat limit comes from the budget, and the cache bound comes from the chat limit

```
budget_mib    = host_ram_mib − os_reserve_mib                  = 32,023 − 2,048 = 29,975
non_chat_mib  = Σ non-chat mem_limits (after D3)               ≈ 18,560
chat_limit    = floor((budget − non_chat) / 6)                 ≈ 1,902 → 1,792 or 2,048 after D3 tuning
cache_ram     = chat_limit − worker_baseline − 256 MiB margin
```

Idle worker baseline is 0.1–0.7 GiB (the weights are on the GPU). That points to **`CACHE_RAM=1024` with a 2,048 MiB chat `mem_limit`** as the starting candidate. At q8_0, Llama-3.1-8B KV is ≈ 68 KiB per token (32 layers × 8 KV heads × 128 dims × K+V × ~1.06 bytes), so 1,024 MiB holds ≈ 15,000 tokens: about 3–4 full HeartCode 4k-token contexts per worker. The measurement (D5) decides whether that is enough. If it isn't, the cache can only grow by shrinking something else in the budget, never by exceeding it.

### D3. Every container gets a limit sized to measured peak plus margin

Proposed non-chat limits, from cgroup `memory.peak` on 2026-09-18:

| Service | Peak | Today | Proposed |
|---|---:|---:|---:|
| embedding-server-4/5 | 322 / 122 | 768 each | 512 each |
| vision-embed-1/2 | 1,684 / 1,536 | 2,560 each | 2,048 each |
| dino-embed-1/2 | 1,156 / 1,329 | 3,072 each | 1,536 each |
| image-server | 4,096 (at limit) | 4,096 | 4,096 (unchanged; watch it) |
| speech-stt | 1,335 | 4,096 | 1,792 |
| speech-tts | 2,278 | 3,072 | 2,816 |
| prometheus, grafana, 3 exporters, speech meter + gateway | ~1,080 total | none | 1,664 total, per service |

That totals ≈ 18,560 MiB. With 6 × 2,048 chat, the sum is ≈ 30,850, about 900 MiB over the 29,975 budget. The implementer closes the gap from measured data, not by guessing. Options in order of preference: trim margins where the measured peak is far below the proposal (STT, TTS, Grafana); use a 1,792 chat limit if D5 shows baseline + cache fits; lower the OS reserve to 1,536 only if host `available` stays above 4 GiB in D6. The budget check (D4) is the arbiter.

`memswap_limit` = `mem_limit` + 512 MiB for every service. A container that outgrows its bound is then killed inside its own memory cgroup (and restarted by Docker) instead of pushing the host into a global OOM that picks a victim at random.

### D4. The budget is declared in compose and enforced in CI

Add an extension field to `gpu-server/docker-compose.yml`:

```yaml
x-host-memory:
  host_ram_mib: 32023
  os_reserve_mib: 2048
```

`scripts/check-memory-budget.py` (stdlib + PyYAML) resolves anchors, then fails on three conditions: a service with no `mem_limit`, a `memswap_limit` below `mem_limit`, or a sum above the budget. It prints the table. It runs in the existing `model-manifest-validate` CI job and has unit tests. It checks the main compose file only; canary compose files must declare what they displace in their own header, and that is out of scope for the check.

*Alternative rejected:* putting the budget in `models.yaml`. That manifest describes model tenancy, while memory limits live in compose, and keeping the check next to the numbers it checks avoids a second source of truth.

### D5. Qualify on one worker before the fleet

Use `pea-gpu-3` (SFW, lowest traffic, 0.6 GiB). Two measurements, taken **direct** against `:8082`, not through LiteLLM:
1. **Is the growth the cache?** With `CACHE_RAM=1024`, drive ≥ 30 distinct multi-turn sessions (`load-tests/` or a small script) and sample `llama-server` VmRSS each minute. Pass when RSS plateaus at ≈ baseline + 1,024 MiB. If RSS keeps climbing past the bound, the growth is not the prompt cache: stop and re-diagnose.
2. **Does reuse still pay?** Alternate two conversations A, B, A, B … (so each return to A must come from the host cache, not the slot). Record the TTFT of each returning turn at `CACHE_RAM=8192` (today) and at `1024`. TTFT is the client wall time of a `max_tokens: 1` request, **not** llama.cpp's `timings.prompt_ms`: the baseline showed `prompt_ms` ≈ 0.12 s on a hit while restoring the cached state takes another ~2.5 s that `prompt_ms` leaves out. `timings.cache_n` still proves hit or miss. Pass when the median TTFT at 1,024 is within 10% of 8,192 for 2 active sessions, and record the curve at 4 and 8 sessions so the cost of thrash is known. If 1,024 fails, try 1,536 and re-run D2.

### D6. Rollout is one worker at a time, through compose

Order: `gpu-server-3` (qualified in D5), then 6, then 2, 1, 5, 4. For each worker: recreate it with `docker compose --env-file .env --env-file models.generated.env up -d gpu-server-N`, wait for `/health` 200, check `docker inspect` (`Config.Cmd` contains `--cache-ram`, `HostConfig.Memory` matches), and let the worker serve for 10 minutes before moving on. Then recreate the non-chat services with their new limits, one at a time. Finally run a sustained load across both routes and check the acceptance criteria.

**Rollback:** revert the compose and env commit and recreate the affected worker. The worker comes back with the 8 GiB default and today's risk, but serving.

## Risks / Trade-offs

- **[1 GiB cache means more cold re-ingests when many sessions share one worker]** → measured in D5 at 2, 4 and 8 sessions. The TTFT gate protects the common case, and the curve documents the tail.
- **[The image server already hits its 4 GiB limit]** → keep 4,096 and add it to the watch list. If it needs more, the budget shows exactly what has to give.
- **[Tight budget blocks adding services later]** → intended. "Add one more worker" should fail CI, not the kernel.
- **[Restarting a worker drops its cache and any in-flight request]** → roll only after checking there is no active HeartCode evaluation, one worker per route at a time. LiteLLM retries a sibling on connection failure.
- **[Wrapper `/health` wedged at 503 after an earlier OOM]** → after rollout, restart any worker that reports busy with no traffic.
- **[The controller inventory lists a stale placement]** → no placement change here, so the inventory is unaffected. Verify with `check-placement.py`.

## Open Questions

- Final `CACHE_RAM` and chat `mem_limit`: 1,024/2,048 is the candidate, and D5 decides.
- ~~Does build 8027 store host-cache entries at q8_0 or f16?~~ Answered by the 2026-09-18 baseline: RSS grew ≈ 65 KiB per cached token, which matches q8_0. 1,024 MiB therefore holds ≈ 16,000 tokens, about 7 sessions of ~2,300 tokens, so the 8-session run is expected to miss.
