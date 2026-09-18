## 0. Interim relief (optional, needs owner go-ahead)

- [ ] 0.1 If host `available` falls below ~2.5 GiB before the fix lands: recreate the largest chat worker (`docker compose up -d --force-recreate gpu-server-N`, one at a time, never two on the same route), wait for `/health`, record RSS before and after. This frees its prompt cache (~7 GiB) until it regrows over the following hours.

## 1. Code

- [x] 1.1 Add `cache_ram: int` (env `CACHE_RAM`) to `gpu-server/config.py`; reject `0` and negative values at startup _(default 8192 = llama.cpp's implicit default made explicit, so shipping the code changes nothing until compose sets a bound)_
- [x] 1.2 Pass `--cache-ram` in `server.py` next to `--cache-reuse`
- [x] 1.3 Unit test: the built command contains `--cache-ram <value>`, and invalid values fail fast _(`tests/test_llama_server_command.py`, 6 tests)_
- [x] 1.4 Add `CACHE_RAM` to the `x-gpu-env-common` environment in `gpu-server/docker-compose.yml` _(`${CACHE_RAM:-8192}`; `gpu-server-3` overrides to `${GPU_3_CACHE_RAM:-1024}` as the qualification worker)_
- [x] 1.5 Add `scripts/prompt-cache-ttft.py`: alternating-session TTFT and distinct-session fill, reporting llama.cpp `timings.cache_n`/`prompt_ms` per turn

## 2. Qualify on one worker (design D5, `pea-gpu-3`)

- [x] 2.1 Record the baseline: RSS, and alternating-conversation TTFT direct against `:8082` at today's default (8,192) for 2, 4 and 8 sessions _(2026-09-18, `evidence/2026-09-18-ttft-cache-ram-8192.json`: ~2,330-token prompts, cold 6.2–6.3 s server-side; returning turns 28/28 cache hits, median wall 2.63–2.67 s, of which only 0.12 s is `prompt_ms` and the rest is restoring the cached state. RSS 859 → 2,920 MiB over 14 sessions ≈ 65 KiB/token, i.e. the cache stores q8_0 KV)_
- [ ] 2.2 Recreate `gpu-server-3` with `CACHE_RAM=1024` (compose override only for this worker); confirm `docker inspect` shows `--cache-ram 1024`
- [ ] 2.3 Drive ≥ 30 distinct sessions; confirm RSS plateaus at ≈ baseline + 1,024 MiB. If not, stop and re-diagnose (the growth is not the cache)
- [ ] 2.4 Repeat the TTFT runs at 1,024; pass if the 2-session median is within 10% of 2.1. Otherwise try 1,536 and redo the D2 arithmetic
- [ ] 2.5 Record the numbers in `evidence/` and fix the final `CACHE_RAM` and chat `mem_limit` in design.md

## 3. Budget and limits

- [ ] 3.1 Add the `x-host-memory` block (`host_ram_mib: 32023`, `os_reserve_mib: 2048`) to `gpu-server/docker-compose.yml`
- [ ] 3.2 Move the chat `mem_limit`/`memswap_limit` into the common anchor (uniform, including `gpu-server-6`), and remove the per-service overrides
- [ ] 3.3 Set the non-chat limits per design D3 (measured peak plus margin), and add limits to the monitoring and speech-helper services that have none; `memswap_limit` = `mem_limit` + 512
- [ ] 3.4 Write `gpu-server/scripts/check-memory-budget.py` plus tests (missing limit, memswap below limit, over budget, anchor resolution); close any remaining gap per D3 until it passes
- [ ] 3.5 Run it in the `model-manifest-validate` CI job
- [ ] 3.6 Rewrite the stale "Memory Budget" comment at the top of `gpu-server/docker-compose.yml` with the real host and the budget table
- [ ] 3.7 Add a correction note to `openspec/changes/archive/2026-09-18-restore-nsfw-chat-capacity/design.md`: "~1.5 GiB per chat container" held only for idle workers; loaded workers reached 7.5–8.5 GiB through the unbounded prompt cache

## 4. Rollout on PEA (design D6)

- [ ] 4.1 Confirm no HeartCode evaluation is running; pull and render on PEA
- [ ] 4.2 Recreate the chat workers one at a time in the order 3, 6, 2, 1, 5, 4: `/health` 200, `docker inspect` Cmd and Memory checked, 10 minutes of serving before the next
- [ ] 4.3 Recreate the non-chat services one at a time with their new limits; confirm health
- [ ] 4.4 Run `check-placement.py`; restart any worker whose `/health` is stuck on 503 `inference_active` with no traffic

## 5. Acceptance

- [ ] 5.1 Run sustained load (≥ 2 h) on both routes; sample `MemAvailable` and per-worker RSS each minute into `evidence/`
- [ ] 5.2 Confirm no `llama-server` OOM kill in `journalctl -k` for the window, `MemAvailable` ≥ 4 GiB throughout, and every RSS below its `mem_limit`
- [ ] 5.3 Update CLAUDE.md "Key Configuration" (memory limits and `CACHE_RAM`)
- [ ] 5.4 Tell the HeartCode side that PEA RAM is bounded, so evaluations can record it as a precondition
