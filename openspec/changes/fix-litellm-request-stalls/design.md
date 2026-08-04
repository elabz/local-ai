# Design — Fix LiteLLM Request Stalls

## Context

LiteLLM (`192.168.0.152:4000`) fronts the llama.cpp replicas on PEA (`192.168.0.144`): three SFW chat replicas (`:8080–8082`), three NSFW (`:8083–8085`), plus embed and speech endpoints. HeartCode's backend is effectively the only client, and it authenticates with a **single** virtual key for every workload — interactive chat, the character-creation wizard, embeddings, and avatar prompt extraction.

Evidence gathered 2026-07-19 (see `proposal.md` for the table):

- A 2-token completion took **52.5 s** through the proxy and **0.62 s** direct to `:8080`, with ~145 ms of llama.cpp compute in both cases.
- The same proxied call was **0.28–0.35 s** minutes later — the fault is intermittent, not a static misconfiguration.
- LiteLLM logged `200 OK` for the slow request. No timeout, retry, or cooldown line. `/health/liveliness` was 200 throughout; all three SFW replicas were 200 on `/health`.
- Concurrently, HeartCode's `POST /wizard/{id}/generate` died with `httpx.ReadTimeout` after ~2 minutes.

The relevant configuration (`litellm/config.base.yaml`):

```yaml
router_settings:
  routing_strategy: "least-busy"
  num_retries: 2
  retry_after: 3
  timeout: 90
  allowed_fails: 1
  cooldown_time: 60
general_settings:
  max_parallel_requests: 9        # per virtual key
  global_max_parallel_requests: 17
  request_timeout: 90
```

Note `litellm/config.yaml` is **generated** from `gpu-server/models.yaml` + `config.base.yaml` by `gpu-server/scripts/render-config.py`. Edits belong in the base file, followed by a re-render and commit; CI fails on drift.

## Goals / Non-Goals

**Goals:**
- Attribute latency to the proxy vs. the model, so "the fleet is slow" and "the proxy is queueing" are distinguishable from metrics alone.
- Confirm or discard the admission-queue hypothesis with evidence before changing behaviour.
- Bound worst-case client-visible latency below HeartCode's client timeouts.
- Make saturation an explicit, retryable signal (`429` + `Retry-After`) rather than an invisible wait.
- Ensure a single transient replica error cannot remove a third of chat capacity for a full minute.

**Non-Goals:**
- Model placement, GPU rebalancing, or tenancy changes (`gpu-server/models.yaml`, the `gpu-rebalance` spec).
- Speech routing (`speech-serving`) — unaffected.
- Raising real fleet throughput. This is about not wasting capacity that already exists, not adding any.
- HeartCode-side retry/backoff and user-facing messaging — companion change in that repo.
- Replacing LiteLLM.

## Decisions

1. **Diagnose before tuning.**
   The stall was not reproducible on demand, and every candidate below is plausible. Shipping a config change now would be guessing, and a config change that appears to work because the intermittent fault simply did not recur is worse than no change — it produces false confidence. So instrumentation lands first, then a reproduction under synthetic concurrent load, then tuning justified by the measurement.
   - *Alternative considered — just raise the limits now:* rejected. If the real cause is a leaked semaphore slot or cooldown flapping, raising `max_parallel_requests` only lengthens the interval between stalls and makes the eventual diagnosis harder.

2. **Proxy overhead is the primary signal.**
   Define overhead as `total_request_duration − upstream_llm_duration`. llama.cpp already returns exact `timings` (`prompt_ms`, `predicted_ms`) in every response, and LiteLLM knows its own end-to-end duration, so the subtraction is well-defined and needs no distributed tracing. A healthy request has overhead in the low tens of milliseconds; the incident had ~52 s. This single number would have identified the problem immediately.
   - *Alternative considered — rely on LiteLLM's built-in latency metrics:* insufficient alone. They report total latency, which is indistinguishable from a genuinely slow generation. The subtraction is what makes it diagnostic.

3. **Fail fast with `429`, do not queue silently.**
   An interactive chat request that cannot start within a couple of seconds is already a bad experience; one that waits 90 s and then times out is strictly worse, because the caller has burned its timeout budget and cannot retry. An explicit queue-wait budget converts a hang into a retryable signal. `Retry-After` gives the client something actionable.
   - *Trade-off:* this makes shedding visible. Callers that previously "succeeded slowly" will now see errors. This is the point — but it means the HeartCode-side handling must land with it, or it reads as a regression. Sequenced in `tasks.md`.

4. **Separate workload classes by key, rather than only raising one number.**
   The wizard holds a slot for 30–60 s per turn; interactive chat needs a slot for a second or two. Sharing one semaphore lets a burst of the former starve the latter — a fairness problem that no single limit value fixes. Distinct virtual keys per workload class give each its own budget, so background generation degrades without taking interactive chat with it.
   - *Alternative considered — raise `max_parallel_requests` to `global_max_parallel_requests`:* simpler, and worth doing regardless, but it only defers the problem: one client can still consume every slot.

5. **Cooldown proportional to the failure.**
   `allowed_fails: 1` + `cooldown_time: 60` means a single connection blip benches a replica for a minute. With three SFW replicas, two near-simultaneous blips leave one replica serving all traffic — which *itself* produces queueing indistinguishable from this incident. The base config's comment justifies aggressive cooldown so "request retries move to a healthy sibling", which is sound for a hard-down replica and harmful for a transient error. Raise `allowed_fails` and/or shorten `cooldown_time`, and prefer a health-driven return over a fixed timer.

6. **Worst-case latency must fit under client timeouts.**
   `num_retries: 2` at `timeout: 90` permits ~270 s plus `retry_after` backoff for a single client request — longer than any HeartCode client timeout, so those retries can only ever produce a client-side timeout, never a successful response. The retry budget and per-attempt timeout must be chosen so the *total* stays under the tightest client timeout, otherwise retrying is pure waste.

## Risks / Trade-offs

- **[The hypothesis is wrong.]** The evidence is circumstantial: intermittent, unlogged, unreproduced. Mitigated by decision 1 — instrumentation must confirm the queue-wait attribution before any tuning is treated as a fix. If overhead turns out to be low during a stall, the cause is elsewhere (aiohttp connection pool, PostgreSQL spend-logging, the `speech_correlation` callback) and this design needs revisiting; those are listed as secondary suspects in Open Questions.
- **[Visible `429`s look like a new outage.]** Load shedding surfaces errors that silent queueing hid. Sequence the HeartCode-side backoff first, and pick the initial queue-wait budget generously, tightening once the metric shows real distribution.
- **[Config edited in the wrong file.]** Editing `litellm/config.yaml` directly is silently reverted by the next render and caught only by CI drift checks. Every task specifies `config.base.yaml` + re-render.
- **[Change applied but not loaded.]** LiteLLM's config is bind-mounted; `docker compose up -d` does **not** reload it. A restart is required, and "verified" must mean verified against the running proxy's effective config, not the file on disk.
- **[Synthetic load misses the real trigger.]** If reproduction requires the specific mix of long wizard generations plus interactive chat, a uniform load test will not trigger it. The reproduction task should mirror the observed mix rather than a flat request rate.

## Migration Plan

1. Land observability (metrics + Grafana panel + alert rules). Purely additive, no behaviour change; safe to deploy immediately.
2. Reproduce under synthetic load resembling the real mix (concurrent long generations + short interactive calls) and confirm the attribution. Record the measured slot-wait distribution.
3. Tune admission and cooldown/retry settings in `config.base.yaml`, re-render, restart LiteLLM, re-measure against step 2's baseline.
4. Introduce fast-fail `429` + `Retry-After`, **after** HeartCode's companion change handles it.
5. Optionally split virtual keys by workload class, coordinated with the HeartCode companion change.

**Rollback:** revert `config.base.yaml`, re-render, `docker compose restart litellm`. Monitoring rules can stay — they are additive and independently useful.

## Open Questions

- Does LiteLLM expose per-key concurrency-slot wait natively, or does the `speech_correlation` callback need extending to record admission timestamps? This determines whether step 1 is config or code.
- Secondary suspects if overhead is *not* in admission: the shared aiohttp session (`SESSION REUSE` appears in the proxy logs — a small connection pool would serialise requests), synchronous PostgreSQL spend-logging on the request path, or the `speech_correlation` callback blocking. Each is cheap to rule out once overhead is measurable.
- Is `global_max_parallel_requests: 17` still the right ceiling given current GPU tenancy, and should it be derived from `gpu-server/models.yaml` rather than hand-maintained, so it cannot drift from actual fleet size?
- Langfuse is documented in both repos at `192.168.0.152:3002` but **no Langfuse container exists on that host** (`docker ps -a` finds none) and it is unreachable. It is not a LiteLLM callback today, so it is not implicated in this stall — but the docs are wrong and should be corrected or the service restored. Tracked separately; noted here so the next person debugging latency does not chase it.
