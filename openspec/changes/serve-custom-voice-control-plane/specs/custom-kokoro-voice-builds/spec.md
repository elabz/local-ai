## MODIFIED Requirements

### Requirement: Build manifests contain validated audio/transcript pairs

The system SHALL load a digest-bound manifest from an opaque intake directory beneath a configured private local root, require every sample to have an opaque ID, root-relative audio and transcript sidecar, checksum, supported metadata, exact transcript, language, and authorization reference, and SHALL reject request-supplied host paths, URLs, symlinks, non-regular files, root escapes, or inconsistent manifests. A build request SHALL name only an intake ID and manifest digest; the only way remote content enters an intake is the signed intake pull, which fetches solely from operator-allow-listed origins.

#### Scenario: Local sample checksum does not match
- **WHEN** a local sample differs from the digest-bound manifest or changes while being copied into the job workspace
- **THEN** validation fails with a safe error, the sample is not decoded, and partial workspace content is removed

#### Scenario: Local path escapes the intake root
- **WHEN** an intake ID or manifest path is absolute, traverses directories, resolves through a symlink, or names a non-regular file
- **THEN** validation fails before content is read and no job is created

#### Scenario: Build request names an intake that does not exist or does not match
- **WHEN** a build is submitted for a missing intake, or with a manifest digest that differs from the intake's sealed manifest
- **THEN** submission is refused with a safe error and no job is queued

## ADDED Requirements

### Requirement: Samples can be pulled into an intake from an allow-listed origin

The control plane SHALL accept a signed `custom-voice-intake-request.v1` naming each sample's role, short-lived fetch URL, SHA-256, transcript, and PCM format, SHALL fetch each URL only when its exact scheme, host, and port are on the operator-configured allow-list, SHALL NOT follow redirects, SHALL enforce the profile's whole-intake byte cap, and SHALL verify each digest and the declared mono 16-bit PCM format before atomically publishing a `benchmark-intake.v1` directory that `prepare_workspace` accepts. A repeat request for the same intake ID with identical content apart from fetch URLs SHALL return the existing manifest digest without fetching; different content SHALL be refused as a conflict.

#### Scenario: A sample URL points outside the allow-list
- **WHEN** any sample's fetch URL names an origin that is not allow-listed
- **THEN** the intake is refused before any URL is fetched and nothing is written

#### Scenario: The origin answers with a redirect or the wrong bytes
- **WHEN** a fetch returns a redirect, a non-200 status, or audio whose digest or format differs from the request
- **THEN** the intake fails with a safe reason code and no intake directory is published

#### Scenario: HeartCode retries with freshly signed URLs
- **WHEN** the same intake is requested again with new fetch URLs and otherwise identical content
- **THEN** the existing manifest digest is returned and no sample is fetched again

### Requirement: Queued builds are driven to a contract result

A host-side runner SHALL claim queued jobs and drive them through workspace preparation, the pinned worker, sealing, compatibility, held-out evaluation, SBOM generation, and review staging, SHALL publish a `BuildResult` containing the artifact identity, SBOM digest and unresolved-licence count, evaluation outcome, compatibility outcome, and preview references, and SHALL end any failure as `failed` with a content-free reason code. Builder containers SHALL NOT receive the Docker socket. A cancellation request SHALL stop the job between phases or, while the worker runs, through the worker's cancellation marker.

#### Scenario: A build succeeds
- **WHEN** every phase completes for a queued job
- **THEN** the job is `succeeded`, its result validates against the contract, and the version is staged but not discoverable

#### Scenario: The worker fails
- **WHEN** the worker exits with a failure reason
- **THEN** the job is `failed` with that safe reason and no result

### Requirement: Job reads and callbacks follow the contract

Job responses SHALL be the contract's `BuildJob` view and SHALL NOT expose internal columns such as caller identity, idempotency keys, or raw stored results. Every job transition SHALL be signalled, best effort, to the job's allow-listed callback as a signed `custom-voice-callback.v1` event carrying no result. A build naming an unknown callback ID SHALL be refused.

#### Scenario: Callback delivery fails
- **WHEN** a callback target is unreachable
- **THEN** the transition still completes and the job remains readable with its authoritative state

### Requirement: Lifecycle operations keep the registry and the serving map consistent

Activation and rollback SHALL verify the registry entry, sealed artifact bytes, SBOM bytes, the digest-bound HeartCode attestation document (approved, internal-Pea scope, bound to both digests, all confirmations, unresolved-licence count equal to the SBOM's), and Kokoro discovery of the provider voice before changing either the registry or the speech gateway's voice map, and SHALL leave both untouched on any failure. Retiring the active version SHALL remove the voice from the serving map before the registry records it retired. Deletion SHALL refuse the active version and SHALL remove the version's artifact and previews before the registry records it deleted.

#### Scenario: The attestation does not match the SBOM
- **WHEN** an activation's attestation states an unresolved-licence count different from the SBOM's
- **THEN** activation is refused and the voice map is unchanged

#### Scenario: The voice is retired
- **WHEN** an administrator retires a voice's active version
- **THEN** the voice is no longer resolvable for speech and no version is active
