## ADDED Requirements

### Requirement: GPU readiness proves current device usability

Every Pea GPU-backed chat and embedding backend SHALL base readiness on the currently configured GPU identity, queryable device memory, loaded model state, and a bounded successful GPU execution check. A stale model-loaded flag or live HTTP event loop SHALL NOT be sufficient for readiness.

#### Scenario: GPU is lost after model startup
- **WHEN** NVML or CUDA reports that the configured GPU is lost or unavailable after the model was loaded
- **THEN** the backend transitions to unavailable immediately and its readiness endpoint returns HTTP 503 with a bounded content-free reason

#### Scenario: Configured identity does not match
- **WHEN** the process-visible GPU UUID differs from its configured UUID
- **THEN** readiness returns HTTP 503 and no inference is admitted on the mismatched device

#### Scenario: GPU and model remain usable
- **WHEN** identity, memory, model, and bounded execution probes all succeed for the required consecutive checks
- **THEN** readiness returns HTTP 200 and reports only safe state and identity metadata

### Requirement: Unavailable GPU backends reject inference

A GPU backend in starting or unavailable readiness state SHALL reject new inference requests with HTTP 503 and a stable safe reason before scheduling model work. It SHALL NOT fall back to CPU or return a successful response from a known-unavailable GPU context.

#### Scenario: Request arrives after device loss
- **WHEN** an embedding or chat request reaches a backend whose GPU readiness is unavailable
- **THEN** the backend returns HTTP 503 without invoking the model

#### Scenario: Device is lost during inference
- **WHEN** CUDA device loss occurs during an admitted request
- **THEN** that request fails, readiness becomes unavailable before another request is admitted, and the failure contains no input or host details

### Requirement: Load balancing excludes GPU-unavailable replicas

Container and LiteLLM health checks SHALL consume GPU-aware readiness so a replica returning HTTP 503 is removed from new-request selection while healthy replicas remain eligible.

#### Scenario: One redundant embedding backend loses its GPU
- **WHEN** one `heartcode-embed-vision` deployment returns GPU-unavailable readiness and another deployment is ready
- **THEN** the unavailable deployment is cooled down and requests are routed to the ready sibling

#### Scenario: Every deployment is unavailable
- **WHEN** all deployments for a public model fail GPU-aware readiness
- **THEN** the routing layer returns an explicit service-unavailable response and does not route to an unhealthy backend or CPU fallback

### Requirement: GPU health recovery is bounded and observable

GPU readiness SHALL fail on the first definitive device-loss, identity, memory, or execution failure and SHALL require at least two consecutive complete successes before returning to ready. Services SHALL expose low-cardinality readiness and failure metrics and SHALL use bounded restart behavior when CUDA context recovery requires process recreation.

#### Scenario: One successful query follows device loss
- **WHEN** an unavailable backend records only one successful recovery probe
- **THEN** it remains unavailable and is not returned to load-balancer rotation

#### Scenario: Recovery succeeds consistently
- **WHEN** the configured GPU passes the required consecutive identity, memory, model, and execution checks
- **THEN** the backend returns to ready and increments a safe recovery counter

#### Scenario: Lost CUDA context requires recreation
- **WHEN** the process cannot safely reuse its CUDA context after a bounded evidence window
- **THEN** it exits for container recreation without claiming readiness during shutdown or entering an unbounded tight restart loop

### Requirement: GPU fault evidence is content-free

GPU health responses, logs, metrics, and alerts SHALL contain only bounded state/reason values, service identity, configured GPU UUID or PCI identity where operationally required, counters, and timings. They SHALL NOT contain prompts, images, embeddings, credentials, model inputs, or unrestricted environment and host data.

#### Scenario: Operator diagnoses an unavailable backend
- **WHEN** an operator inspects health, metrics, alerts, and bounded logs
- **THEN** they can distinguish query, identity, memory, execution, and model failure without accessing protected request content

### Requirement: Failed GPU recovery is bounded and persistent

The host SHALL attempt to reinitialize a failed GPU and restart all containers mapped to its physical slot. It SHALL persist recovery attempts across process and host restarts and SHALL stop automatically after three failed attempts for the same GPU UUID.

#### Scenario: Recovery succeeds
- **WHEN** reset and mapped-container restart restore every required serving port before the third failed attempt
- **THEN** the controller clears the failure state, removes quarantine, and leaves every mapped service healthy

#### Scenario: Three attempts fail
- **WHEN** the same GPU UUID cannot restore all mapped services after three recovery attempts
- **THEN** the controller opens a durable circuit breaker and makes no further automatic attempt until the UUID changes or an operator explicitly clears state

### Requirement: Failed serving ports return 503 independently of GPU startup

Every serving port mapped to a quarantined GPU slot SHALL accept HTTP connections and return a bounded HTTP 503 response for all paths and methods even when NVIDIA CDI cannot start the model containers.

#### Scenario: GPU is absent at cold start
- **WHEN** a configured UUID is absent and its GPU containers cannot be created
- **THEN** all mapped model-serving ports return HTTP 503 without loading a model or using CPU fallback

### Requirement: Hardware failure escalation uses Slack safely

After the third failed attempt the controller SHALL send one Slack notification to `#hardware-alerts` containing the failed GPU UUID and PCI address. It SHALL NOT expose the webhook, credentials, prompts, model inputs, or unrestricted host data.

#### Scenario: Circuit breaker opens
- **WHEN** attempt three fails for a GPU UUID
- **THEN** exactly one alert is sent for that failure generation and subsequent checks do not repeat it

### Requirement: GPU inventory survives replacement and boot

The system SHALL persist the current PCI-slot-to-UUID inventory in JSON, archive the prior inventory when a replacement UUID is detected, and record failed or replaced UUIDs in a separate JSON history. A boot after power-down and replacement SHALL regenerate runtime GPU placement and start every container mapped to all detected slots.

#### Scenario: Replacement appears in the same slot
- **WHEN** a new UUID is enumerated at a configured PCI address
- **THEN** the old inventory is archived, the old UUID is recorded, the current inventory and compose override use the new UUID, recovery attempts reset, and all mapped containers are started
