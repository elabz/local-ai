## ADDED Requirements

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
