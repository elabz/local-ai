## Context

The PEA chat wrapper runs a background watchdog every 15 seconds. Its llama.cpp health request has a five-second timeout, and three consecutive exceptions cause an unconditional process exit. Docker then restarts the container because its policy is `unless-stopped`.

During sustained three-worker extraction on 2026-08-18, llama.cpp continued returning successful completions while health probes timed out. The watchdog nevertheless restarted all three `heartcode-chat-sfw` backends. LiteLLM logged downstream connection failures and returned HTTP 500 after exhausting two retries. Docker showed no OOM kill. GPU memory remained within device capacity. The restart counters—304, 293, and 265—show that this failure mode predates the observed workload.

Rollout investigation found a second failure hidden by Docker's container-level
`OOMKilled=false`: under sustained load the kernel can kill the llama.cpp child
inside the 2 GiB memory cgroup while leaving the Python PID 1 alive. Acceptance
therefore also requires SFW wrapper memory headroom sized from observed RSS;
this is distinct from GPU-memory capacity and from the false HTTP-probe loop.
The deployed host has 16 GiB RAM and 16 GiB swap rather than the stale 32 GiB
RAM assumption in compose comments. The chat wrapper therefore does not use
llama.cpp `--mlock`; GPU-offloaded model pages remain reclaimable under host
pressure instead of forcing child or unrelated-service OOM kills.

## Goals / Non-Goals

**Goals:**
- Keep healthy-but-busy inference backends running.
- Detect and recover from a dead llama.cpp child within a bounded interval.
- Route around a restarting or unavailable backend.
- Preserve enough structured evidence to distinguish saturation, timeout, process death, GPU failure, and operator restart.
- Prove behavior with sustained-load and fault-injection tests.

**Non-Goals:**
- Changing the served models or their sampling defaults.
- Increasing aggregate GPU capacity.
- Hiding overload by permitting unbounded queues or retries.
- Altering speech or embedding health semantics unless they share the same demonstrated defect.

## Decisions

### Decision 1: Process state is the primary liveness signal

The watchdog SHALL treat an exited llama.cpp child as a genuine liveness failure. A delayed HTTP `/health` response alone SHALL NOT prove process death. HTTP health remains a readiness/degradation signal and may trigger routing withdrawal, but restart requires stronger evidence such as child exit, repeated failed probes while no inference is active, or a bounded stuck-request condition.

This prevents active inference from being mistaken for process failure while retaining deterministic recovery when the child actually exits.

### Decision 2: Health checks are occupancy-aware and stateful

The wrapper SHALL track in-flight inference and expose explicit states such as `starting`, `ready`, `busy`, `degraded`, and `unavailable`. Probe failures during active requests move the backend to `busy` or `degraded` without consuming the same restart budget as idle probe failures. State transitions and reasons are exported as metrics and structured logs.

An implementation may use a longer health timeout, a dedicated non-blocking llama.cpp endpoint, process inspection, or a combination. Merely increasing the current timeout is an acceptable emergency mitigation but not the complete design.

### Decision 3: Recovery is bounded and avoids restart storms

Genuine failure recovery SHALL include a backoff or restart-rate circuit breaker. Repeated restarts within a defined window withdraw the backend and alert rather than cycling indefinitely. Recovery criteria and operator intervention steps SHALL be documented.

### Decision 4: LiteLLM routes around unhealthy deployments

The HeartCode model group SHALL place connection-failing or restarting deployments into cooldown long enough for startup and model loading. Retries within one client request SHOULD select a different eligible deployment. If none is available, the proxy returns a bounded, classifiable unavailable response rather than amplifying retries across every recovering backend.

### Decision 5: Validation reproduces both load and real failure

Acceptance requires two distinct tests:

1. Sustained concurrent inference long enough to cross multiple watchdog windows, with no load-induced restart and no avoidable proxy 500.
2. Deliberate llama.cpp child termination or equivalent fault injection, demonstrating withdrawal, bounded restart, readiness recovery, and successful proxy traffic afterward.

## Risks / Trade-offs

- **A genuinely wedged child remains alive longer** → use a bounded stuck-request detector and idle probe failure threshold rather than HTTP timeout alone.
- **Busy backends continue accepting excess work** → expose readiness separately and let LiteLLM stop routing new work while existing requests finish.
- **Long cooldown reduces capacity** → base cooldown on measured model-load time and verify recovery automatically.
- **Fault injection affects live clients** → run on a canary backend or within an announced maintenance window.
- **Metrics cardinality grows** → use bounded reason enums, model group, and backend ID; never request or prompt identifiers.

## Migration Plan

1. Capture a baseline of restart and proxy-error rates under controlled load.
2. Implement stateful, occupancy-aware watchdog behavior behind a configuration flag.
3. Deploy to one SFW canary backend and run sustained-load plus fault-injection acceptance.
4. Configure LiteLLM cooldown/failover and verify retry routing against the canary.
5. Roll out across the remaining SFW backends while monitoring restart and 5xx rates.
6. Document rollback: disable the new watchdog mode and restore the prior proxy routing policy.

## Open Questions

- Does the deployed llama.cpp build expose a liveness endpoint that remains responsive while all inference slots are occupied?
- What idle failure duration distinguishes a wedged child from normal long generation on the P104-100 hardware?
- Should repeated restart suppression require operator intervention or permit a slower automated recovery probe?
- What LiteLLM cooldown duration best matches observed model reload time without unnecessarily shrinking capacity?
