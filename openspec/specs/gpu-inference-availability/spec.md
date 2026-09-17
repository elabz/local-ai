# gpu-inference-availability Specification

## Purpose
TBD - created by archiving change prevent-load-induced-gpu-restarts. Update Purpose after archive.
## Requirements
### Requirement: Busy inference does not trigger a liveness restart

The PEA chat wrapper SHALL distinguish a live backend occupied by inference from a dead or irrecoverably wedged llama.cpp child. HTTP health-probe delay during active inference SHALL NOT, by itself, trigger a container restart.

#### Scenario: Health probe times out while inference succeeds
- **WHEN** a llama.cpp health probe exceeds its timeout while an inference request is active and the child process remains alive
- **THEN** the backend enters a bounded busy or degraded state without restarting
- **AND** successful in-flight inference is allowed to complete

#### Scenario: Sustained concurrent load
- **WHEN** supported concurrent inference runs across at least five watchdog intervals
- **THEN** no backend restarts solely because health probes were delayed by that workload

### Requirement: Genuine child failure recovers within a bounded interval

The wrapper SHALL withdraw and restart a backend when the llama.cpp child exits or meets the documented stuck-child criteria. Repeated failure SHALL be subject to restart backoff or circuit breaking.

#### Scenario: Child process exits
- **WHEN** the llama.cpp child exits unexpectedly
- **THEN** the backend becomes unavailable to routing
- **AND** a bounded restart is attempted
- **AND** readiness is restored only after the model can serve requests

#### Scenario: Repeated restart failure
- **WHEN** a backend exceeds the configured restart-rate threshold
- **THEN** further rapid restart cycling is suppressed
- **AND** an operator-visible alert identifies the backend and bounded failure reason

### Requirement: Proxy retries route around unavailable deployments

LiteLLM SHALL place connection-failing or restarting HeartCode deployments into cooldown and SHOULD select another eligible deployment for a retry.

#### Scenario: One backend restarts
- **WHEN** a HeartCode backend becomes unreachable during a request and another deployment is healthy
- **THEN** the failing deployment enters cooldown
- **AND** a bounded retry is routed to another eligible deployment

#### Scenario: No deployment is available
- **WHEN** all deployments in the model group are starting, unavailable, or in cooldown
- **THEN** the proxy returns a bounded, classifiable unavailable response
- **AND** it does not amplify retries indefinitely

### Requirement: Health and restart evidence is observable without request content

The runtime SHALL expose bounded metrics and structured logs sufficient to distinguish busy probe timeout, idle probe failure, child exit, GPU failure, restart decision, restart suppression, and recovery.

#### Scenario: Load-induced probe delay
- **WHEN** a health probe is delayed while inference is active
- **THEN** observability records the backend state and bounded reason without prompts, responses, credentials, or user identifiers

#### Scenario: Restart-rate regression
- **WHEN** backend restarts or downstream connection-error 5xx responses exceed the configured operational threshold
- **THEN** an alert identifies the affected model group and backend

### Requirement: Busy backends queue within a bound and signal busy distinctly

A chat backend whose inference slots are all occupied SHALL hold an arriving request for up to `ADMISSION_WAIT_SECONDS` (default sized to one worst-case generation, not zero) and admit it when a slot frees. Only when the bound is exceeded SHALL it respond, and that response SHALL be HTTP 429 with a `Retry-After` header and a `BACKEND_BUSY` body. HTTP 503 SHALL be reserved for a backend that cannot serve at all (GPU unavailable, child dead, downstream timeout).

#### Scenario: Second request during generation
- **WHEN** a request arrives while the only slot is generating and the slot frees within the wait bound
- **THEN** the request is admitted and completes without any error response

#### Scenario: Wait bound exceeded
- **WHEN** no slot frees within `ADMISSION_WAIT_SECONDS`
- **THEN** the backend returns 429 with `Retry-After` and increments a `rejected` admission metric
- **AND** it does not return 503

### Requirement: Proxy cooldown is reserved for unavailable deployments

LiteLLM SHALL NOT place a deployment into cooldown because it reported busy (429 `BACKEND_BUSY`); it SHALL retry on another deployment when one exists or return the busy response with `Retry-After` when none does. Cooldown SHALL require more than one connection-level or 503 failure within the window (`allowed_fails` ≥ 3) and SHALL last no longer than a typical generation (`cooldown_time` ≤ 30 s). Per-model `timeout` SHALL be at least the admission wait plus the worst-case generation time.

#### Scenario: Single replica, two overlapping requests
- **WHEN** a model group has one deployment and two requests overlap
- **THEN** the second waits for the slot and neither request causes a cooldown

#### Scenario: Transient 503 from one replica
- **WHEN** one deployment returns a single 503 and other deployments are healthy
- **THEN** the request is retried elsewhere and the deployment remains routable

### Requirement: Consumer keys are concurrency-capped

Every LiteLLM API key SHALL carry `max_parallel_requests` no greater than the total slot count of the model groups it may call. Batch consumers SHALL be capped at their agreed worker count (Rediska: 4). The client contract (bounded concurrency, honour `Retry-After`, jittered exponential backoff, no fan-out beyond slot count) SHALL be documented and linked from the key-issuance procedure.

#### Scenario: Batch client fans out
- **WHEN** a key capped at 4 issues 7 concurrent requests
- **THEN** at most 4 reach backends at once and the rest receive 429 with `Retry-After` from the proxy without touching any deployment
