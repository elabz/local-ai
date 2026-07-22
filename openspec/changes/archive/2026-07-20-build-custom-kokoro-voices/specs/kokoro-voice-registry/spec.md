## ADDED Requirements

### Requirement: Custom voice versions are immutable registry entries

The registry SHALL map reserved stable voice IDs to immutable artifact versions and digests with explicit staged, active, unhealthy, retired, and deleted states.

#### Scenario: Stable ID collides with a built-in voice
- **WHEN** a staging request uses a built-in or invalid voice ID
- **THEN** the registry rejects it without changing any pack or mapping

### Requirement: Staging does not publish a voice

The system SHALL permit protected evaluation of a staged compatible artifact without exposing it through public voice discovery or ordinary synthesis.

#### Scenario: HeartCode stages a completed build
- **WHEN** the artifact is staged for admin review
- **THEN** protected previews remain available but ordinary users cannot discover or request its stable ID

### Requirement: Activation is exact, healthy, and atomic

The system SHALL activate only the requested version and digest and SHALL switch the stable ID only after the pinned Kokoro provider loads it and passes a synthesis health probe.

#### Scenario: New pack fails its health probe
- **WHEN** activation cannot produce valid audio
- **THEN** activation fails, the previous mapping remains active, and public discovery does not advertise the failed version

### Requirement: Active custom voices preserve the inference contract

Healthy active custom voices SHALL be usable through existing voice discovery and `/v1/audio/speech` without changing authentication, streaming, response formats, built-in voices, or the accepted `opus-40k` profile.

#### Scenario: Client synthesizes with an active custom voice
- **WHEN** an authenticated speech request names its stable ID
- **THEN** Kokoro uses the active artifact and returns audio through the existing response contract

### Requirement: Rollback reactivates a prior known-good version

The registry SHALL retain eligible prior versions and support the same health-checked atomic switch for rollback.

#### Scenario: Operator rolls back a degraded version
- **WHEN** rollback names the prior active version and digest
- **THEN** it becomes active after a successful health probe without changing the stable ID

### Requirement: Registry drift fails closed

The system SHALL reconcile declared registry state with installed and loaded artifact digests and SHALL mark mismatched or missing active entries unhealthy rather than serving an unverified pack.

#### Scenario: Loaded pack digest differs from registry
- **WHEN** reconciliation detects the mismatch
- **THEN** the voice is removed from discovery or rejected for synthesis, operators are alerted, and other voices remain available

### Requirement: Deletion is reference-aware and verifiable

The system SHALL prevent deletion of active or retained rollback artifacts and SHALL verify removal of eligible raw caches, previews, workspaces, artifacts, and registry references according to retention policy.

#### Scenario: Deletion is requested for the active version
- **WHEN** the version still serves a stable voice ID
- **THEN** deletion is rejected until it is retired or replaced and all protected references are detached
