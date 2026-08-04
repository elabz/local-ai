# LLM Request Admission — Delta

## ADDED Requirements

### Requirement: Bounded Admission Wait
The system SHALL bound the time a request may wait for a concurrency slot. A request that cannot be admitted within the configured budget SHALL be rejected with HTTP 429 and a `Retry-After` header, rather than continuing to wait until the request timeout expires. The admission budget SHALL be short relative to the request timeout, so a shed request leaves the caller enough of its own timeout budget to retry.

#### Scenario: Slot available
- **WHEN** a request arrives and a concurrency slot is free
- **THEN** it is dispatched upstream immediately and no rejection occurs

#### Scenario: Saturated beyond the admission budget
- **WHEN** no slot becomes free within the admission budget
- **THEN** the request is rejected with 429 and a `Retry-After` value, and no upstream inference call is made

#### Scenario: Brief contention absorbed
- **WHEN** no slot is free but one is released within the admission budget
- **THEN** the request is dispatched normally rather than rejected, so ordinary short contention does not surface as an error

### Requirement: Concurrency Budget Sized To Fleet Capacity
Per-key concurrency budgets SHALL permit a legitimate client to use the fleet's actual serving capacity. A single client using one virtual key SHALL NOT be capped below the global budget purely because its traffic shares one key. Where distinct workload classes have materially different slot-holding times, they SHALL be separable into independent budgets so that slow background work cannot exhaust the allowance needed by interactive traffic.

#### Scenario: Single-key client with an idle fleet
- **WHEN** one client sends concurrent requests through a single virtual key while the fleet is otherwise idle
- **THEN** it can occupy the fleet's available capacity, rather than being limited to a per-key allowance well below it

#### Scenario: Background work does not starve interactive traffic
- **WHEN** long-running background generations occupy their workload class's full budget
- **THEN** interactive requests in a different workload class are still admitted against their own budget

### Requirement: Proportional Replica Cooldown
Replica cooldown SHALL be proportional to the evidence of failure. A single transient error SHALL NOT remove a replica from rotation for a period long enough to materially reduce group capacity, and a recovered replica SHALL be returned to rotation when it is observed healthy rather than only after a fixed timer elapses. Cooldown of a persistently failing replica SHALL still occur.

#### Scenario: Transient error
- **WHEN** a replica returns a single connection error and then serves healthy requests
- **THEN** it is not withheld from rotation long enough to meaningfully reduce the group's serving capacity

#### Scenario: Persistently failing replica
- **WHEN** a replica fails repeatedly
- **THEN** it is removed from rotation and traffic is routed to healthy siblings

#### Scenario: Capacity preserved under blips
- **WHEN** transient errors occur on more than one replica in a group within a short window
- **THEN** the group retains enough replicas in rotation to serve traffic without queueing

### Requirement: Retry Budget Bounded By Client Timeout
The total time a single client request may consume across all upstream attempts, including per-attempt timeouts and inter-attempt backoff, SHALL be bounded below the tightest timeout used by calling services. Retries that could only complete after the caller has already abandoned the request SHALL NOT be attempted.

#### Scenario: Retries fit within the caller's timeout
- **WHEN** an upstream attempt fails and retries remain
- **THEN** the retries are attempted only while the accumulated elapsed time leaves room to return a response before the caller's timeout

#### Scenario: Budget exhausted
- **WHEN** the accumulated elapsed time would exceed the caller's timeout
- **THEN** no further attempt is made and an error is returned promptly instead of consuming the remaining budget
