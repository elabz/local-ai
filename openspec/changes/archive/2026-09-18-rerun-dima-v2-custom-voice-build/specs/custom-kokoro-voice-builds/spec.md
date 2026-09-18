## ADDED Requirements

### Requirement: Failed non-resumable builds are rerun without losing evidence

When a build exits without a valid result and its checkpoint lacks the complete versioned state required for deterministic resume, the system SHALL preserve the failed attempt and safe terminal reason, SHALL NOT represent the checkpoint as a completed artifact or faithful resume point, and SHALL require any rerun to use a distinct job, workspace, output, lock, and idempotency identity.

#### Scenario: Timed-out build has only a best-voice checkpoint
- **WHEN** a worker exits with `worker_timeout`, has no valid result or artifact, and its checkpoint lacks completed-step, score, and random-generator state
- **THEN** the attempt remains failed and preserved, and a retry is created under a new isolated identity rather than overwriting or falsely resuming it

#### Scenario: Operator inspects prior failure evidence
- **WHEN** an authorized operator prepares the rerun
- **THEN** the system exposes only the prior job's safe state, reason, opaque identity, checkpoint metadata, and digests without exposing transcripts, audio, credentials, or private paths in telemetry

### Requirement: Recovery reruns preserve authorized inputs and declared quality policy

A recovery rerun SHALL use a digest-bound plan that explicitly records whether its manifest, adaptation selection, exclusions, held-out set, seed, fitness-text count, search-step target, builder identity, and evaluation thresholds match or differ from the failed attempt. Any change SHALL be deliberate and auditable, and held-out samples SHALL remain inaccessible to construction.

#### Scenario: Dima v2 strict rerun is prepared
- **WHEN** the timed-out Dima v2 attempt is rerun
- **THEN** the plan retains seed 137, accepted adaptation samples `adapt-002` through `adapt-006`, exclusion of `adapt-001`, four construction-inaccessible held-outs, three fitness texts, 6,000 steps, and a 0.68 held-out speaker-similarity gate

#### Scenario: Rerun deadline is increased
- **WHEN** the prior attempt exhausted its six-hour deadline while otherwise making progress
- **THEN** the rerun may record a ten-hour deadline while retaining live-speech priority, concurrency, health, GPU admission, VRAM reserve, cancellation, and quality requirements

### Requirement: Reruns require safe preflight and durable monitoring

Before launching a recovery rerun, the system SHALL verify pinned worker/model availability, exact plan and input identity, workspace isolation, restrictive access, GPU capacity, absence of a conflicting build, and live-TTS health. The launched job SHALL be observable independently of a client session through content-free worker, checkpoint, result, resource, failure, and TTS-health evidence.

#### Scenario: Preflight detects an occupied rerun destination
- **WHEN** the proposed rerun workspace, output, lock, or worker identity already exists unexpectedly
- **THEN** launch fails closed without modifying the failed attempt or the occupied destination

#### Scenario: Conversational session is cleared during training
- **WHEN** the client session that initiated the rerun is no longer available
- **THEN** an authorized new session can recover the worker state, checkpoint freshness, safe terminal outcome, and TTS health from durable project and Pea state without accessing private content

#### Scenario: Live TTS becomes unhealthy
- **WHEN** monitoring detects that the production TTS health guardrail is no longer satisfied during the rerun
- **THEN** offline construction yields or stops according to the configured guardrail while active Dima v1 service remains unchanged

### Requirement: A rerun cannot replace the active voice before qualification

A completed rerun SHALL remain inactive until its result identities and step count are valid, clean compatibility passes, held-out evaluation satisfies the declared thresholds, immutable artifact and supply-chain evidence are produced, authenticated internal-use approval is recorded, staging succeeds, and activation is verified through provider, registry, gateway, audio, and HeartCode consumer layers.

#### Scenario: Dima v2 construction or evaluation fails
- **WHEN** the rerun times out, produces invalid output, fails compatibility, or scores below the strict held-out threshold
- **THEN** Dima v2 is not activated and Dima v1 remains active and selectable

#### Scenario: Dima v2 passes all gates
- **WHEN** the rerun completes 6,000 steps, passes compatibility and strict held-out evaluation, receives matching internal-use approval, stages, activates, and passes end-to-end verification
- **THEN** the stable `custom-dima` identity resolves to the exact v2 artifact and v1 is retired only through that successful activation transition
