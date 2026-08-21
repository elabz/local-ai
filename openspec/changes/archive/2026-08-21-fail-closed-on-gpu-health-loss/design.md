## Context

Pea GPU services expose HTTP health endpoints consumed by Docker and LiteLLM. The shared llama wrapper already checks its child `llama-server`, but Python embedding services currently report healthy whenever their model object's `loaded` flag is true. Their detached NVML metrics thread logs GPU failures without changing readiness, so `pea-embed-vision-2` remained HTTP 200 after its configured P104 returned `GPU is lost`.

This failure is not isolated to one card. Repository history records `GPU-f1fa6009` failing at PCI `04:00.0` on 2026-07-09 with repeated `RmInitAdapter` failures. The replacement `GPU-8d0782` subsequently failed at the same PCI address on 2026-07-20 with AER physical-layer evidence and Xid 79. Software health behavior must protect routing regardless of the physical root cause; the repeated slot/riser fault is tracked as an operational maintenance issue.

LiteLLM already enables active health checks, one-failure cooldown, retries, and least-busy routing. Returning 503 from a model-aware health endpoint is therefore the missing signal for withdrawing a degraded replica. GPU services must not silently use CPU because that would appear healthy while violating latency and placement requirements.

## Goals / Non-Goals

**Goals:**

- Make GPU readiness reflect current device identity and usable execution, not only startup state.
- Withdraw a bad replica before new inference is admitted and return a stable HTTP 503 response during degradation.
- Cover shared llama chat servers and Python vision/DINO/multimodal embedding services with consistent semantics.
- Preserve low-cardinality, content-free observability and provide deterministic fault-injection tests.
- Recover automatically only when the process still owns valid CUDA state; otherwise exit for bounded container recreation.

**Non-Goals:**

- Diagnosing or repairing the PCI slot, riser, GPU, cabling, or PSU.
- Automatically moving a model to another GPU or editing UUID placement.
- CPU fallback, reduced model quality, or changing public LiteLLM model names.
- Treating temperature alone as proof of GPU loss.

## Decisions

### 1. Use one fail-closed readiness state machine

Each GPU-backed process will maintain `starting`, `ready`, or `unavailable` state with a bounded safe reason enum such as `gpu_query_failed`, `gpu_identity_mismatch`, `gpu_execution_failed`, or `model_unavailable`. An identity, memory, or execution failure transitions to unavailable immediately. Readiness returns only after two consecutive successful probes; counters reset on any failure.

This is preferred over using the existing `model_loaded` gauge because loaded weights can remain referenced after CUDA context loss. It is also preferred over parsing log strings because NVML/CUDA calls provide direct process-local evidence.

### 2. Combine device identity with a bounded execution probe

At startup and periodically thereafter, Python GPU services will verify that CUDA is available, the visible device UUID matches the configured UUID when supplied, device memory can be queried, and a tiny no-input-derived tensor operation plus synchronization succeeds. The probe is serialized with model inference to avoid racing the CUDA context. The llama wrapper will combine its child health with an NVML/`nvidia-smi` identity-and-memory probe because the wrapper does not depend on Torch.

A telemetry scrape failure alone may be transient, but the same query used for readiness is fail-closed because an unqueryable assigned GPU cannot be proven safe. Recovery hysteresis prevents a single successful query from flapping a backend into rotation.

### 3. Separate liveness from readiness and gate inference

`/health` remains the model-aware readiness endpoint used by Docker and LiteLLM and returns 503 with a safe reason when unavailable. A lightweight `/live` endpoint may return 200 while the process event loop is alive so operators can distinguish a wedged process from lost GPU readiness. Every inference route checks the same readiness state before parsing or scheduling work and returns 503 when unavailable.

This is preferred over relying only on Docker health because requests can arrive between health-check intervals. It also avoids returning 500, which describes an unexpected request failure rather than a known unavailable backend and may not trigger the intended load-balancer behavior.

### 4. Exit only for non-recoverable CUDA-context loss

When a Python execution probe reports a lost/invalid CUDA device, the service marks readiness unavailable immediately and exits after a short bounded evidence window so Docker can recreate it. Query timeouts or identity mismatches remain unavailable without an immediate crash, allowing diagnosis and preventing restart storms. The existing llama watchdog continues to exit after consecutive child failures, while the new GPU probe can independently withdraw readiness earlier.

Because Xid 79 normally requires reset or host intervention, container recreation may not restore service; it is still bounded and never makes the failed replica eligible.

Live rollout confirmed a colder failure mode: when the configured UUID is absent from host enumeration, NVIDIA CDI rejects container creation before the Python readiness server can start. That state is still fail-closed and LiteLLM excludes the deployment, but it produces connection failure rather than an application-level 503. Returning a bounded 503 for this cold-absent case would require a GPU-independent supervisor or quarantine sidecar and is not implemented by this change.

### 5. Use existing LiteLLM active health checking

LiteLLM retains `enable_health_check`, `allowed_fails: 1`, retries, cooldown, and least-busy routing. Implementation tests will confirm its health probe targets the backend readiness endpoint and that a 503 deployment is cooled down while a healthy sibling serves traffic. Static model configuration remains the source of backend membership; this change supplies correct health evidence rather than dynamically rewriting configuration.

The deployed LiteLLM 1.81.9 image (`sha256:ea96c62abb3f2d4939a147173a056bdde84809c9553c25ccf04660122fe95b5e`) does not support a per-deployment `health_check_url` or `health_check_path`. Its active OpenAI health check sends a bounded synthetic chat or embedding request. The backend inference-admission check therefore supplies the readiness signal: an unavailable GPU returns 503 before model invocation, and LiteLLM records that deployment unhealthy. Live verification on 2026-07-21 reported one healthy and one unhealthy `heartcode-embed-vision` deployment and routed a bounded embedding to the healthy sibling. The compose tag remains floating and should be replaced with an immutable release or digest separately.

DINO is image-only, while LiteLLM 1.81.9 health-checks embedding deployments with a text input. Its deployments therefore use `health_check_model: openai/heartcode-embed-visual-health`. DINO admits only that exact health model with LiteLLM's exact bounded health input, after GPU readiness admission, and returns a synthetic dimension-correct vector without invoking the image model. All ordinary text inputs remain rejected.

### 6. Record safe metrics and physical-slot evidence

Services will export readiness as a gauge and transitions/failures as counters labeled only by bounded state/reason and configured server identity. Alerts fire on unavailable readiness even if the HTTP process and `model_loaded` gauge remain up. Operations documentation will record both `04:00.0` incidents with their distinct UUIDs and require slot/riser/power-path inspection before trusting another replacement card there.

### 7. Persist recovery state by physical slot

A root systemd controller will treat PCI address as the stable hardware slot identity and UUID as the replaceable board identity. A JSON inventory maps each slot to its current UUID, compose services, container names, and serving ports. On discovery of a different UUID at the same PCI address, the controller archives the prior inventory, records the displaced UUID in a failed-ID history, atomically updates the current inventory, and writes a generated JSON Compose override for the new UUID.

Recovery attempts are durable across controller and host restarts. For a failed slot the controller stops all mapped containers, attempts a bounded NVIDIA or PCI function reset when the device is addressable, and starts every mapped compose service. A slot receives at most three failed recovery attempts until its UUID changes or an operator explicitly clears its state.

### 8. Quarantine ports independently of CUDA

GPU-bound containers cannot return 503 when NVIDIA CDI rejects process creation. The controller therefore owns lightweight host HTTP quarantine listeners. After a failed recovery attempt it stops the affected containers and binds every configured serving port; all methods and paths return a bounded JSON 503. Before another recovery attempt it closes those listeners so compose can bind the production ports. Quarantine contains no CUDA, model, request logging, or fallback behavior.

### 9. Alert once after the third failure

After the third failed recovery attempt, the controller opens the durable circuit breaker and posts one Slack message to `#hardware-alerts` through `SLACK_WEBHOOK_URL`. The message contains only the logical slot, failed GPU UUID, PCI address, attempt count, and bounded reason. The webhook is loaded from a root-readable mode-600 environment file and is never stored in Git, logs, JSON inventory, or command output.

### 10. Reconcile on boot and replacement

The systemd unit starts after Docker and NVIDIA persistence. At startup the controller inventories GPUs, adopts any replacement UUID at its configured PCI slot, generates the compose override, starts all mapped GPU services, verifies their serving ports, and quarantines any slot that cannot recover. This permits a clean power-down, board replacement, and power-up without hand-editing every UUID in compose.

## Risks / Trade-offs

- [A probe briefly contends with inference] → Use a tiny operation, serialize it with the existing model lock, and run at a bounded interval rather than per token or batch.
- [Transient NVML failure removes a healthy backend] → Prefer a short false-negative withdrawal over routing to an unverified GPU; require consecutive successes for recovery and retain healthy siblings.
- [All replicas share a host-level fault] → Return 503 rather than fall back to CPU; surface a critical alert and preserve explicit failure.
- [Container restart loops on Xid 79] → Bound automatic exits/restarts and document host maintenance escalation after repeated failure.
- [LiteLLM health semantics differ by version] → Add an integration test against the pinned LiteLLM configuration and verify live routing before rollout.
- [A model-specific path bypasses admission] → Inventory every GPU inference route and enforce the shared dependency/middleware plus route-level tests.

## Migration Plan

1. Add fault-injection fixtures and the shared readiness state machine with health behavior disabled behind a default-off environment gate.
2. Wire Python embedding services, then the shared llama wrapper, and run healthy plus simulated NVML/CUDA-loss tests.
3. Enable GPU-aware health on one redundant embedding replica and verify Docker marks it unhealthy and LiteLLM routes to its sibling during injected failure.
4. Roll out to remaining chat and embedding replicas one at a time without restarting unrelated GPU services.
5. Verify healthy inference, forced 503 withdrawal, recovery hysteresis, alerts, and no CPU fallback.
6. Roll back by disabling the GPU-aware gate and restoring the prior images; retain new metrics and incident documentation.

## Open Questions

- Which pinned LiteLLM health-check request path is used for custom OpenAI embedding backends, and does it require an explicit per-deployment health URL?
- Should repeated `gpu_query_failed` trigger process exit, or remain unhealthy indefinitely to preserve diagnostics until an operator acts?
- What restart-count threshold should escalate from container recreation to a host-level maintenance alert?
