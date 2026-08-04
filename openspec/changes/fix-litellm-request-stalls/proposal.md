# Fix LiteLLM Request Stalls

## Why

Requests through the LiteLLM proxy intermittently take **tens of seconds to minutes** while the GPU fleet is idle and every health check is green. Measured on 2026-07-19 from the HeartCode dev host:

| Path | Wall clock | llama.cpp compute (from `timings`) |
|---|---|---|
| Direct to replica `192.168.0.144:8080` | **0.62 s** | ~127 ms |
| Same request via LiteLLM `192.168.0.152:4000` | **52.5 s** | ~145 ms |
| Same request via LiteLLM, minutes later | 0.28–0.35 s | ~145 ms |

Both requests were a 2-token completion (`"Say OK"`, `max_tokens: 5`). The model did ~145 ms of work in both cases; the other ~52 s was spent inside the proxy. It is **intermittent** — the same call was sub-second minutes later — and it leaves **no trace**: LiteLLM logged a normal `200 OK`, no timeout, no retry, no cooldown. `/health/liveliness` returned 200 throughout and all three SFW replicas returned 200 on `/health`.

This is not cosmetic. During the stall window, HeartCode's character-generation wizard failed outright with `httpx.ReadTimeout` → HTTP 500, after ~2 minutes. Anything with a longer prompt than a trivial ping exceeds its client timeout. Users see a broken feature; the fleet reports itself perfectly healthy.

The leading suspect is **admission control, not the GPUs**. `litellm/config.base.yaml` sets:

```yaml
max_parallel_requests: 9          # per API key
global_max_parallel_requests: 17
request_timeout: 90
```

`max_parallel_requests` is enforced **per virtual key**, and HeartCode drives all of its traffic — chat, wizard, embeddings, avatar prompts — through a *single* virtual key. So all HeartCode traffic contends for one 9-slot semaphore, and LiteLLM **queues** requests past that limit rather than rejecting them. A handful of concurrent long generations (wizard turns run 30–60 s each and hold their slot the whole time) saturates all 9 slots, and every subsequent request waits — silently, with no log line and no metric — until a slot frees or `request_timeout: 90` fires. The comment above those settings sizes them for the fleet ("6 chat GPUs * 2 concurrent each = 12, + 1 embed + 4 speech = 17"), but a single-key client can never reach 17; it is capped at 9 no matter how idle the GPUs are.

Two settings likely amplify it: `allowed_fails: 1` with `cooldown_time: 60` benches a replica for a full minute after one connection error (with 3 SFW replicas, two blips leave one replica serving everything), and `num_retries: 2` at `timeout: 90` turns one stuck attempt into a multi-minute request.

**This hypothesis is not yet confirmed** — the stall was not reproducible on demand, and the current instrumentation cannot distinguish "queued for a slot" from "waiting on the GPU". Making that distinction observable is the first deliverable, not an afterthought.

## What Changes

- **Make queue wait measurable.** Today a request that spends 52 s in an admission queue and one that spends 52 s on a GPU are indistinguishable from outside. Export per-request proxy overhead (total latency minus upstream latency) and per-key concurrency-slot occupancy/wait, so the hypothesis above can be confirmed or discarded with data.
- **Bound the wait instead of hiding it.** A request that cannot get a slot within a short, explicit budget SHALL fail fast with `429` + `Retry-After` rather than queueing invisibly toward a 90 s timeout. A caller that is told "busy, retry" can back off and show a useful message; a caller that hangs for 90 s cannot.
- **Size concurrency to the fleet, per key.** Raise/replace the single-key `max_parallel_requests` cap so one legitimate client can use the fleet's real capacity, and/or split HeartCode's traffic across purpose-specific virtual keys (interactive chat vs. background generation) so a burst of slow wizard calls cannot starve interactive chat.
- **Stop one blip from halving capacity.** Re-tune `allowed_fails` / `cooldown_time` so a transient connection error does not bench a healthy replica for a full minute, and reconsider `num_retries: 2` × `timeout: 90`, whose worst case exceeds every client timeout in HeartCode.
- **Alert on the failure mode.** A Prometheus alert SHALL fire when proxy overhead or queue wait crosses a threshold while GPU utilisation is low — the exact signature of this incident, and the thing no existing check catches.

Out of scope: model/tenancy changes (that is `gpu-server/models.yaml`), GPU rebalancing, and anything in the HeartCode repo. Client-side timeout/retry tuning in HeartCode is a **companion change** in that repo, not this one.

## Capabilities

### New Capabilities

- `llm-request-admission`: Bounded, observable admission control for the LiteLLM proxy — per-key concurrency sized to real fleet capacity, an explicit queue-wait budget, fast `429` rejection with `Retry-After` instead of silent queueing, and replica cooldown/retry settings that degrade proportionally rather than collapsing capacity after a single error.
- `llm-latency-observability`: Metrics and alerting that attribute request latency to the proxy vs. the model — per-request proxy overhead, per-key slot occupancy and queue wait, and an alert for the "slow proxy, idle GPUs, green health checks" signature that current liveness and per-replica health checks cannot detect.

### Modified Capabilities

<!-- None. `gpu-rebalance` and `speech-serving` are unaffected: this change touches
     router/admission settings and monitoring only, not model placement or speech routing. -->

## Impact

- **`litellm/config.base.yaml`** — the hand-maintained source for router/general settings. All admission and retry knobs change here, **not** in `litellm/config.yaml`, which is generated by `gpu-server/scripts/render-config.py` and must be re-rendered and committed.
- **`monitoring/prometheus/`** — new recording/alert rules. Prometheus already scrapes `litellm:4000` (job `litellm`) and the GPU servers, so the alert needs no new scrape target. A Grafana panel for proxy overhead vs. GPU utilisation is a natural addition to the existing dashboards.
- **Possible new virtual keys.** If traffic is split by workload class, HeartCode needs a second key and a corresponding env var; that is the companion change on the HeartCode side (`INFERENCE_API_KEY` plus a background/batch key). Coordination checkboxes in `tasks.md`.
- **Deployment.** LiteLLM's config is bind-mounted and does **not** reload on `docker compose up -d` — applying this requires an explicit `docker compose restart litellm` on Prod (`192.168.0.152`).
- **Risk of the fast-fail change.** Converting silent queueing into `429`s makes load shedding *visible*: callers that previously waited will now see errors until they implement backoff. That is the intent, but it must land together with the HeartCode-side retry handling or it will look like a regression.
- **Rollback.** Revert `config.base.yaml`, re-render, restart LiteLLM. No schema or data migration; monitoring rules are additive and safe to leave in place.
