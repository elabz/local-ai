## 1. Fault Fixtures and Shared Readiness

- [x] 1.1 Add deterministic GPU probe fixtures for healthy identity/memory/execution, query failure, UUID mismatch, device loss, and recovery hysteresis.
- [x] 1.2 Implement a thread-safe fail-closed readiness state machine with bounded states/reasons, immediate failure, and two-success recovery.
- [x] 1.3 Add safe readiness/failure/recovery Prometheus metrics without request content, host paths, or unrestricted exception values.

## 2. Python Embedding Services

- [x] 2.1 Add a periodic Torch/NVML GPU probe to vision-embed that verifies configured UUID, memory query, tiny execution, and synchronization under the model lock.
- [x] 2.2 Make vision-embed `/health` return 503 when GPU readiness is not ready, add `/live`, and reject embeddings before model invocation while unavailable.
- [x] 2.3 Mark readiness unavailable when inference raises a CUDA/device-loss error and retain content-free error responses.
- [x] 2.4 Apply the same readiness and inference-admission behavior to DINO and multimodal embedding services.
- [x] 2.5 Add route and lifecycle tests proving stale `loaded` state cannot mask GPU failure and no CPU fallback occurs.

## 3. Shared Llama Chat Wrapper

- [x] 3.1 Add a bounded configured-UUID and GPU-memory probe that does not require Torch to the shared chat wrapper.
- [x] 3.2 Combine child-model health with GPU readiness for `/health`, expose `/live`, and reject completion/chat requests with 503 while unavailable.
- [x] 3.3 Integrate GPU probe failures with the existing watchdog without creating an unbounded restart loop.
- [x] 3.4 Add tests for healthy child plus lost GPU, UUID mismatch, failed child, recovery, and inference admission.

## 4. Routing and Operations

- [x] 4.1 Confirm the pinned LiteLLM health-check behavior for OpenAI chat and embedding deployments and add any required explicit health paths.
- [x] 4.2 Add integration tests showing a 503 replica is cooled down while a healthy sibling serves, and all-unavailable returns service unavailable.
- [x] 4.3 Update Docker health checks and environment configuration with explicit expected GPU UUIDs and the default-off rollout gate.
- [x] 4.4 Add critical alerts for GPU readiness loss and repeated restart/recovery failure.
- [x] 4.5 Document both distinct GPU UUID failures at PCI `04:00.0`, the suspected slot/riser/power path, safe triage, and rollback.

## 5. Verification and Rollout

- [x] 5.1 Run unit, route, security, and fault-injection tests across chat, vision, DINO, and multimodal services.
- [x] 5.2 Build affected images and run healthy preflight plus simulated query, identity, and execution failures without production traffic.
- [x] 5.3 Enable GPU-aware readiness on one redundant embedding replica and verify Docker health plus LiteLLM sibling routing.
- [x] 5.4 Roll out one replica at a time, verify healthy inference and metrics, and retain CPU fallback disabled.
- [x] 5.5 Probe the currently failed GPU backend to confirm it returns 503 and is not selected while its healthy sibling continues serving.

## 6. Persistent Hardware Recovery and Quarantine

- [x] 6.1 Add a PCI-keyed JSON GPU inventory, archived inventory rotation, failed-UUID history, and atomic generated Compose override.
- [x] 6.2 Implement a durable three-attempt recovery state machine that resets an addressable GPU and restarts every mapped container without an unbounded loop.
- [x] 6.3 Add GPU-independent quarantine listeners that return bounded HTTP 503 on every mapped serving port and release ports before recovery.
- [x] 6.4 Add one-shot Slack `#hardware-alerts` escalation after attempt three with only GPU UUID, PCI address, attempt count, and safe reason.
- [x] 6.5 Add replacement detection and boot reconciliation that adopts a new UUID at the same PCI address and starts all mapped services.
- [x] 6.6 Add deterministic tests for reset/restart success, three failures, persisted circuit breaker, 503 on all ports, one-shot Slack, inventory rotation, and replacement boot.
- [x] 6.7 Install the controller on Pea with a mode-600 webhook environment file, enable it at boot, and verify the current failed GPU reaches quarantine after exactly three bounded attempts.
- [x] 6.8 Power-cycle or equivalent boot-path verification after replacement-capable reconciliation is installed, then verify all detected GPUs and mapped containers initialize cleanly.
