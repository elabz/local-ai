## ADDED Requirements

### Requirement: Admission and timeout bounds derive from the capacity model

`ADMISSION_WAIT_SECONDS`, LiteLLM per-model `timeout`, and `Retry-After` values SHALL be derived from the published per-group generation time and slot count and SHALL be updated when those figures change.

#### Scenario: Slot count doubles
- **WHEN** a chat group is re-qualified at two slots per replica
- **THEN** the admission wait and proxy timeout for that group are recomputed and committed with the capacity table
