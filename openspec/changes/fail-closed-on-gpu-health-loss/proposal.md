## Why

Pea can continue returning HTTP 200 from a model health endpoint after NVML reports `GPU is lost`, leaving a backend eligible for load-balancer traffic even though CUDA inference is no longer trustworthy. This is now an observed production failure on `pea-embed-vision-2`, and the same PCI `04:00.0` path has lost two different P104 cards, so health must fail closed on runtime GPU faults rather than only checking that a model object was loaded at startup.

## What Changes

- Add a shared, bounded GPU-readiness state that distinguishes startup, ready, degraded, and lost-device conditions without exposing host or workload details.
- Make GPU-backed health/readiness endpoints return HTTP 503 when the configured GPU cannot be queried, its UUID/placement differs, CUDA reports a lost device, or a bounded execution probe fails.
- Reject new inference requests with HTTP 503 and a stable safe reason while GPU readiness is degraded, instead of attempting work on a known-bad device or falling back to CPU.
- Update container and load-balancer health checks so failed GPU readiness removes the affected chat or embedding replica from rotation.
- Add recovery hysteresis: a backend becomes ready again only after repeated identity, memory, and execution checks pass; a process holding invalid CUDA state exits for container recreation when recovery requires it.
- Add low-cardinality GPU fault metrics and alerts plus tests for NVML loss, CUDA loss, UUID mismatch, stale model-loaded state, transient telemetry errors, and healthy recovery.
- Document the repeated PCI `04:00.0` incident and require physical-slot/riser investigation separately from software recovery.
- Add a host-level, persistent recovery controller that attempts GPU reset and restarts every mapped container no more than three times before opening a circuit breaker.
- Serve GPU-independent HTTP 503 quarantine responses on every affected model port while its GPU stack cannot start.
- Persist PCI-slot-to-UUID inventory, archive prior inventories, record failed UUIDs, detect replacement GPUs, and regenerate runtime placement so a powered-down host starts cleanly after replacement.
- Send a single credential-safe Slack alert to `#hardware-alerts` after the third failed recovery attempt, including the failed GPU UUID and PCI address.

## Capabilities

### New Capabilities

- `gpu-fault-health`: GPU-aware readiness, inference admission, load-balancer withdrawal, safe observability, and bounded recovery behavior for Pea GPU model backends.

### Modified Capabilities

- `gpu-rebalance`: Strengthen the existing no-dead-routes requirement so every routed chat and embedding backend must pass GPU-aware readiness, not merely expose a running HTTP process.

## Impact

- Affects shared chat-server health/watchdog code under `gpu-server`, vision/DINO/text embedding health paths, Docker health checks, Prometheus alerts, and LiteLLM/load-balancer backend eligibility.
- Health and inference endpoints gain stable HTTP 503 failure behavior for unavailable GPU execution; successful API shapes and public model names do not change.
- No CPU fallback, automatic GPU reassignment, model relocation, or physical repair is introduced by this change.
- The controller may adopt a replacement UUID only at the same configured PCI slot; it does not move workloads between slots.
