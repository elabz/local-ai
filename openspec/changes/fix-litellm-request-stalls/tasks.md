# Tasks — Fix LiteLLM Request Stalls

> Ordering is deliberate: **measure, reproduce, then tune.** Section 3 changes
> behaviour and must not be attempted before section 2 confirms the cause —
> a tuning change that "works" because an intermittent fault did not recur is
> worse than no change.

## 1. Observability (additive, safe to deploy immediately)

- [ ] 1.1 Determine whether LiteLLM exposes per-key concurrency-slot occupancy and admission wait natively on `/metrics`; if not, extend `litellm/speech_correlation.py` (or add a sibling callback) to record request-accepted and upstream-dispatch timestamps
- [ ] 1.2 Export proxy overhead per request: total duration minus upstream duration, taking upstream duration from the llama.cpp `timings` fields (`prompt_ms` + `predicted_ms`) already present in every response; label by model group and virtual key
- [ ] 1.3 Export per-key and global concurrency budget occupancy, and admission wait duration, as distinct series
- [ ] 1.4 Add Prometheus recording rules for overhead and admission-wait percentiles (`monitoring/prometheus/`); the `litellm` scrape job already exists — no new target needed
- [ ] 1.5 Add an alert for sustained high proxy overhead / admission wait **while** GPU utilisation is low, and verify it does **not** fire when latency is high because the fleet is genuinely busy
- [ ] 1.6 Add a Grafana panel plotting proxy overhead against GPU utilisation so the two are comparable at a glance
- [ ] 1.7 Deploy and confirm metrics appear: edit under `monitoring/`, then `docker compose restart litellm` on Prod (`192.168.0.152`) — the bind-mounted config does **not** reload on `up -d`

## 2. Reproduce and confirm the cause

- [ ] 2.1 Build a load scenario in `load-tests/` mirroring the observed traffic mix — concurrent long generations (30–60 s, wizard-like) alongside short interactive completions — rather than a flat request rate
- [ ] 2.2 Run it against a single virtual key and record whether admission wait accounts for the added latency while GPU utilisation stays low
- [ ] 2.3 Record the measured slot-wait distribution as the baseline that section 3 must improve on
- [ ] 2.4 **Decision gate:** if overhead is *not* in admission, stop and re-diagnose against the secondary suspects in `design.md` (shared aiohttp session pool, synchronous PostgreSQL spend-logging, `speech_correlation` callback) — sections 3–5 assume the admission hypothesis and must not be applied on a wrong diagnosis
- [ ] 2.5 Confirm from the running proxy's effective config (not the file on disk) which limits were actually in force during the reproduction

## 3. Admission and routing tuning

> All edits go in `litellm/config.base.yaml`, **never** `litellm/config.yaml` —
> the latter is generated and CI fails on drift.

- [ ] 3.1 Raise the per-key concurrency budget so a single-key client is not capped below the fleet's real capacity; re-render via `gpu-server/scripts/render-config.py` and commit the regenerated `litellm/config.yaml`
- [ ] 3.2 Re-tune `allowed_fails` / `cooldown_time` so one transient error does not bench a replica long enough to reduce group capacity; prefer health-driven return over a fixed timer where supported
- [ ] 3.3 Re-tune `num_retries` × `timeout` so worst-case total elapsed time fits under the tightest HeartCode client timeout (currently the wizard's), rather than the present ~270 s ceiling that can only ever produce a client timeout
- [ ] 3.4 Restart LiteLLM on Prod and re-run the section 2 scenario; compare against the 2.3 baseline
- [ ] 3.5 Confirm the direct-vs-proxied latency gap measured in `proposal.md` (0.62 s vs 52.5 s) no longer reproduces under load

## 4. Fast-fail admission

> **Do not land before the HeartCode companion change (5.1).** Converting silent
> queueing into visible 429s without caller-side backoff reads as a new outage.

- [ ] 4.1 Configure a bounded admission budget, short relative to `request_timeout`, after which a request is rejected rather than continuing to wait
- [ ] 4.2 Ensure rejection returns HTTP 429 with a `Retry-After` header and makes no upstream inference call
- [ ] 4.3 Verify brief contention is still absorbed — a slot freed within the budget results in normal dispatch, not a 429
- [ ] 4.4 Verify under the section 2 load that shedding is proportionate: 429s appear only at genuine saturation, not during ordinary bursts

## 5. Cross-repo coordination (HeartCode)

- [ ] 5.1 **HeartCode companion change** — handle 429 + `Retry-After` from the proxy with backoff, and surface a retryable "busy, try again" state instead of a hard failure (mirrors the existing avatar `busy` 503 UX)
- [ ] 5.2 If workload classes are split by key (decision 4 in `design.md`), provision a second virtual key and add the corresponding env var on the HeartCode side, routing background/wizard traffic separately from interactive chat
- [ ] 5.3 Re-check HeartCode's client timeouts against the retry budget agreed in 3.3 so the two are consistent in both directions

## 6. Documentation

- [ ] 6.1 Document the admission model in `litellm/README.md`: what each budget governs, how per-key and global budgets interact, and why the per-key value is what it is
- [ ] 6.2 Add a runbook entry for the "slow proxy, idle GPUs, green health checks" signature — the direct-to-replica vs. through-proxy comparison is the fastest way to localise it and should be written down
- [ ] 6.3 Note in `CLAUDE.md` that LiteLLM config changes require an explicit `docker compose restart litellm`, not `up -d`

## 7. Follow-up (tracked, not blocking)

- [ ] 7.1 Langfuse is documented in both repos at `192.168.0.152:3002`, but **no Langfuse container exists on that host** and the endpoint is unreachable. It is not a LiteLLM callback today, so it is not implicated in this stall — either restore the service or correct the docs in `CLAUDE.md` (both repos) and `CLAUDE.local.md`, so the next person debugging latency does not chase it
- [ ] 7.2 Consider deriving `global_max_parallel_requests` from `gpu-server/models.yaml` rather than hand-maintaining it, so the ceiling cannot drift from actual fleet size
