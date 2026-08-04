# LLM Latency Observability — Delta

## ADDED Requirements

### Requirement: Proxy Overhead Attribution
The system SHALL expose, per completion request, the latency attributable to the proxy as distinct from the latency attributable to the model, computed as total request duration minus upstream inference duration. Upstream duration SHALL be taken from the values the inference server reports (llama.cpp `timings.prompt_ms` + `timings.predicted_ms`) rather than estimated. The metric SHALL be labelled by model group and by virtual key so a stall can be attributed to a workload class.

#### Scenario: Healthy request
- **WHEN** a completion is served while the fleet is not saturated
- **THEN** the recorded proxy overhead is a small fraction of total request duration, and total duration tracks the reported inference duration

#### Scenario: Stalled request with an idle fleet
- **WHEN** a completion takes tens of seconds while the inference server reports only milliseconds of compute
- **THEN** the recorded proxy overhead accounts for the difference, identifying the proxy rather than the model as the source of the delay

#### Scenario: Genuinely slow generation
- **WHEN** a long generation legitimately occupies the model for tens of seconds
- **THEN** proxy overhead remains small and the latency is attributed to the model, not the proxy

### Requirement: Admission Queue Visibility
The system SHALL expose the occupancy of each concurrency budget and the time requests spend waiting for admission before being dispatched upstream. Metrics SHALL distinguish per-key budgets from the global budget, so exhaustion of one client's allowance is distinguishable from exhaustion of total fleet capacity.

#### Scenario: Per-key budget exhausted while global capacity remains
- **WHEN** one virtual key holds all of its permitted concurrent slots but the global budget is not exhausted
- **THEN** the metrics show that key's budget at full occupancy with non-zero admission wait, while the global budget shows spare capacity

#### Scenario: Admission wait recorded
- **WHEN** a request cannot be dispatched immediately because no slot is free
- **THEN** the elapsed time between request acceptance and upstream dispatch is recorded as admission wait

### Requirement: Saturation Alerting
The system SHALL alert when sustained proxy overhead or admission wait coincides with low GPU utilisation — the signature of capacity being withheld by the proxy while the fleet is idle. This condition SHALL be detectable even when liveness endpoints and per-replica health checks all report healthy, since those checks pass throughout such an incident.

#### Scenario: Silent stall detected
- **WHEN** proxy overhead exceeds its threshold for a sustained period while GPU utilisation stays low and all health checks report healthy
- **THEN** an alert fires identifying proxy admission as the suspected cause

#### Scenario: Busy fleet does not alert
- **WHEN** requests are slow because GPU utilisation is genuinely high
- **THEN** the proxy-overhead alert does not fire, because the latency is attributed to the model rather than the proxy
