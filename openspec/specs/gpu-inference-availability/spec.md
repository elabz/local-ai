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

