# Handoff: Pea host RAM OOM — unbounded llama.cpp host prompt cache

**From:** HeartCode session, 2026-09-18 (found while running the `dedupe-history-scaffolds` chat-quality evaluation)
**For:** the agent working in `local-ai`
**Status:** diagnosed, **nothing changed on Pea or in this repo**. The fix is yours.
**Filed:** moved here from `docs/pea-host-ram-oom-handoff.md` on 2026-09-18 as evidence for this change; links updated for the archived `restore-nsfw-chat-capacity`.

## TL;DR

The Pea host (`192.168.70.144`, 31 GB RAM) is running out of RAM under chat load, and the
kernel is killing `llama-server`. Every chat worker is started **without `--cache-ram`**, so
llama.cpp build 8027 uses its default host-RAM prompt cache of **8192 MiB per server**. Six
workers can therefore grow to ~48 GiB of anonymous memory on a 31 GB host. The 8 GiB
per-container `mem_limit`s do not prevent this — each caps one worker, but together they
allow 42 GiB. Bound the cache in `gpu-server/server.py`, make the limits sum below physical
RAM, and verify `--cache-reuse` TTFT did not regress.

## Evidence (all collected 2026-09-18)

### Two host-level OOM kills during a four-hour evaluation

```
$ journalctl -k --since "2026-09-18 08:00" | grep "Out of memory: Killed process"
Sep 18 11:16:35 pea kernel: Out of memory: Killed process 1666430 (llama-server) total-vm:59088664kB, anon-rss:7608992kB
Sep 18 12:42:53 pea kernel: Out of memory: Killed process 1668718 (llama-server) total-vm:58996476kB, anon-rss:7514860kB
```

- `oom-kill:constraint=CONSTRAINT_NONE` on the 12:42 kill — the **whole host** ran out, not a
  container's memcg.
- The victims held **~7.5 GB of anonymous memory** and only ~95 MB file-backed
  (`file-rss:95240kB`). This is not the mmapped GGUF; it is memory the process allocated.
- The 12:42 kill took out `pea-gpu-1`/`pea-gpu-2` (both restarted at 12:43; `pea-gpu-2`
  `RestartCount=1`). The HeartCode backend's pre-token retry absorbed it, so no user-visible
  error — but a kill after the first token would surface as a mid-stream failure.

### Memory grows with use, toward the cache default

Per-worker `llama-server` RSS at ~13:40Z (`/proc/<pid>/status` VmRSS) against the container limit:

| Container | Route | mem_limit | llama-server RSS |
|---|---|---:|---:|
| pea-gpu-1 | SFW | 8 GiB | **8.3 GiB** |
| pea-gpu-2 | SFW | 8 GiB | 1.2 GiB (restarted 12:43) |
| pea-gpu-3 | SFW | 8 GiB | 0.6 GiB |
| pea-gpu-4 | NSFW | 8 GiB | **7.3 GiB** |
| pea-gpu-5 | NSFW | 8 GiB | **7.6 GiB** |
| pea-gpu-6 | NSFW | **2 GiB** | 0.1 GiB |

Workers that have served a lot of traffic sit near 7.5–8.3 GiB. Idle or freshly restarted
ones sit at 0.1–1.2 GiB. Every non-chat container on the host (embeds, speech STT/TTS,
image, monitoring) totals **under 1 GB** — the chat workers are the whole problem.

Host at that moment: `free -m` → 32023 total, 28121 used, **3901 available**. Close to the next kill.

### The cache default, confirmed on the running build

```
$ docker exec pea-gpu-1 llama-server --version
version: 8027 (25224c802)

$ docker exec pea-gpu-1 llama-server --help | grep -A2 cache-ram
-cram, --cache-ram N   set the maximum cache size in MiB (default: 8192, -1 - no limit, 0 - disable)
                       (https://github.com/ggml-org/llama.cpp/pull/16391)
```

Running command line of `pea-gpu-1` (no `--cache-ram`):

```
llama-server --model /models/Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf --host 127.0.0.1 --port 8081
  --n-gpu-layers 33 --ctx-size 16384 --override-kv llama.context_length=int:16384
  --batch-size 128 --ubatch-size 64 --threads 2 --parallel 1 --cont-batching
  --cache-reuse 256 --cache-type-k q8_0 --cache-type-v q8_0 --jinja
```

### Where it comes from in this repo

- `gpu-server/server.py:54` builds the `llama-server` args from `gpu-server/config.py`
  settings. It passes `--cache-reuse` (`config.py:25`, `cache_reuse = 256`) and **never
  passes `--cache-ram`**.
- `gpu-server/docker-compose.yml`: `gpu-server-1..5` set `mem_limit: 8192m`. `pea-gpu-6`
  inherits the `x-gpu-server-common` anchor's **`mem_limit: 2048m` / `memswap_limit: 3072m`**
  with no override (it came back to NSFW duty on 2026-09-17 via `fa67067`). With an 8 GiB
  cache default it will be memcg-killed at 2 GiB as soon as it serves real traffic.
- The **"Memory Budget" comment at the top of `gpu-server/docker-compose.yml` is stale**: it
  describes a 16 GB host, 5 GB SFW / 2 GB NSFW workers, and "actual use much lower".
- [restore-nsfw-chat-capacity/design.md](../../archive/2026-09-18-restore-nsfw-chat-capacity/design.md) (8/9) justified re-adding a worker
  with "a chat container uses ~1.5 GiB RSS with an 8 GiB ceiling" and "14 GiB available".
  That was true of idle workers; under load it is false. That premise is what tipped the
  host over.

## What is verified vs. inferred

- **Verified:** the OOM kills and their anonymous RSS; build 8027; the 8192 MiB `--cache-ram`
  default; that no worker sets it; per-worker RSS growth with use; the limits' sum
  (5 × 8 GiB + 2 GiB = 42 GiB > 31 GB).
- **Inferred, verify first:** that the anonymous growth *is* the host prompt cache (rather
  than, say, a leak in the wrapper). The shape fits — it plateaus near 8 GiB and scales with
  traffic — but prove it: set `--cache-ram` on one worker, drive traffic, and confirm RSS
  plateaus near the new bound.

## Recommended fix

1. **Bound the cache.** Add `cache_ram: int` (MiB) to `gpu-server/config.py` and pass
   `--cache-ram` in `server.py` next to `--cache-reuse`. Suggested starting value
   **2048 MiB**, to be confirmed by step 4. Keep it a setting (env `CACHE_RAM`) so it can
   be tuned per worker without a code change.
2. **Make the limits add up.** With a bounded cache, a worker should peak at roughly
   baseline (~1 GiB) + cache. Set every chat worker's `mem_limit` to a consistent backstop
   (e.g. `4096m` with a 2048 MiB cache), **including `pea-gpu-6`**, which currently has no
   override. Target: sum of all container limits ≤ ~28 GiB on the 31 GB host, leaving OS headroom.
3. **Rewrite the stale budget comment** in `gpu-server/docker-compose.yml` with the real host
   (31 GB) and real numbers, and correct the ~1.5 GiB premise in
   [restore-nsfw-chat-capacity/design.md](../../archive/2026-09-18-restore-nsfw-chat-capacity/design.md).
4. **Measure that `--cache-reuse` still pays.** `--cache-reuse` is documented as requiring
   prompt caching, and HeartCode depends on it. Its layered memory varies the prompt between
   turns, and without reuse the whole prompt is re-ingested. Earlier measurement on a canary:
   repeated-prompt TTFT 5.27 s cold → 2.61 s cached, direct. Repeat that direct against one
   worker (not through LiteLLM, which adds ~1.2 s) at the old and new `--cache-ram`. Do
   **not** use `--cache-ram 0` without this measurement — it may disable the reuse path.
5. **Guard it.** `enforce-capacity-guardrails` already validates the manifest in CI
   (`render-config.py`, `model-manifest-validate`). Add a check that the sum of Pea
   `mem_limit`s stays under physical RAM, so the next "add one more worker" fails CI instead
   of the kernel.

Suggested vehicle: a new change (e.g. `bound-llama-host-prompt-cache`), since this is
neither `prevent-load-induced-gpu-restarts` (health-probe false positives,
`OOMKilled=false`) nor `restore-nsfw-chat-capacity` (placement). Cross-reference both.

## Rollout traps on Pea

- **The GPU controller reverts ad-hoc container changes.** `pea-gpu-controller.service`
  re-runs `docker compose up -d` for a slot's services about 60 s after they stop, from the
  live inventory at `/var/lib/pea-gpu-controller/current-inventory.json`. Change compose (and
  the inventory if placement changes); do not `docker stop` or hand-`docker run` a worker.
- **Running containers drift from compose.** Check `docker inspect <c> --format '{{.Config.Cmd}}'`
  and `{{.HostConfig.Memory}}` after rollout; do not trust the file.
- **An OOM mid-request can wedge the wrapper's `/health`** at 503 `inference_active` forever
  while the container keeps serving. After the fix, restart any worker whose health reads
  busy with no traffic.
- **Keep build 8027.** Do not "fix" this by moving llama.cpp versions; streaming Qwen3
  broke on other builds and 8027 is pinned deliberately.
- **Roll one worker at a time** so each route (SFW 1–3, NSFW 4–6) keeps serving.

## Coordination with HeartCode

- A HeartCode evaluation is live on the SFW route until roughly **15:30Z on 2026-09-18**.
  Restarting `pea-gpu-1..3` or LiteLLM before it finishes aborts in-flight turns. It is done
  when `openspec/changes/v1-character-chat-quality/evidence/2026-09-18-candidate-e-orchestrator.log`
  in the heartcode repo ends with `candidate E evaluation complete`. NSFW workers 4–6 are
  used only by the last (full-corpus) run.
- Nothing needs to change on the HeartCode side. Once this lands, tell the HeartCode side
  so future evaluations can record "Pea RAM bounded" as a precondition. The chat-quality
  runs in August were invalidated by this same failure class.
- Out of scope here, but related: workers run `--ctx-size 16384` while HeartCode's context
  budget is 4096. The prompt cache stores KV state per cached prompt, so a smaller context
  would also shrink its footprint. That is `raise-context-window`'s decision, not this fix's.

## Acceptance

- No `Out of memory: Killed process … (llama-server)` in `journalctl -k` across a sustained
  load run on both routes (e.g. the HeartCode chat-quality corpus, or `load-tests/`).
- Every chat worker's RSS plateaus below its `mem_limit`, and the limits sum below ~28 GiB.
- `free -m` "available" stays above ~4 GiB at peak.
- Repeated-prompt TTFT with `--cache-reuse`, measured direct, within ~10% of the pre-change value.
- `pea-gpu-6` has the same memory configuration as the other NSFW workers.
