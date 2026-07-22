## ADDED Requirements

### Requirement: Builder release is evidence-based

The system SHALL permit implementation and benchmarking of a restricted
sample-to-voice-pack pilot before quality acceptance, but SHALL release or activate its artifacts only
after compatible artifacts, acceptable quality, permissible licensing, bounded
resource use, acceptable live-TTS impact, and explicit human approval are
recorded under versioned thresholds.

#### Scenario: No candidate meets the thresholds
- **WHEN** every evaluated technique fails compatibility, quality, licensing, capacity, or live-latency requirements
- **THEN** the feasibility milestone records a no-release outcome and no artifact is activated or represented as accepted custom-voice training

#### Scenario: One authorized speaker is available for a restricted pilot
- **WHEN** the system has one production-authorized speaker with separate adaptation and held-out samples
- **THEN** it may build and benchmark a speaker-specific pilot but does not claim generalization to arbitrary speakers

### Requirement: The pilot uses multiple references reproducibly

The `kvoicewalk-multireference.v1` profile SHALL compute a normalized target
speaker centroid from every adaptation recording, SHALL exclude all held-out
recordings from construction and tuning, SHALL record the random seed and pinned
builder revision, and SHALL emit deterministic build metadata for each walk.

#### Scenario: Pilot constructs a candidate
- **WHEN** a validated manifest contains adaptation and held-out samples
- **THEN** all adaptation samples contribute to the target centroid, no held-out sample is opened during construction, and the result records its seed and input manifest digest

### Requirement: Build APIs are private and scoped

The system SHALL expose voice-build operations only through a private authenticated control plane with scoped authorization, rate limits, and replay protection, separate from public Kokoro and LiteLLM inference routes.

#### Scenario: General inference credential submits a build
- **WHEN** a client authenticated only for speech inference requests a voice build
- **THEN** the request is denied and no local input is opened or job created

### Requirement: Build manifests contain validated audio/transcript pairs

The system SHALL load a digest-bound manifest from an opaque intake directory beneath a configured private local root, require every sample to have an opaque ID, root-relative audio and transcript sidecar, checksum, supported metadata, exact transcript, language, and authorization reference, and SHALL reject request-supplied host paths, URLs, symlinks, non-regular files, root escapes, or inconsistent manifests.

#### Scenario: Local sample checksum does not match
- **WHEN** a local sample differs from the digest-bound manifest or changes while being copied into the job workspace
- **THEN** validation fails with a safe error, the sample is not decoded, and partial workspace content is removed

#### Scenario: Local path escapes the intake root
- **WHEN** an intake ID or manifest path is absolute, traverses directories, resolves through a symlink, or names a non-regular file
- **THEN** validation fails before content is read and no job is created

### Requirement: Preprocessing publishes an immutable private workspace

The system SHALL copy digest-verified regular intake files through no-follow
descriptors into a per-job `0700` workspace, detect source identity or metadata
changes during copy, enforce owner/mode and byte quotas, decode measured PCM
metadata, and deterministically create mono 24 kHz PCM16 derivatives without
overwriting source recordings. The selected pilot profile SHALL require six
adaptation and four held-out samples, supported language, 5–35 seconds per
sample, non-empty bounded UTF-8 transcripts, acceptable level/silence and
speaking-rate plausibility, and safe per-sample findings.

#### Scenario: Valid production intake is prepared
- **WHEN** all ten digest-bound samples satisfy the selected profile
- **THEN** an atomic private workspace and digest-bound build plan are published, with adaptation and held-out roles preserved

#### Scenario: Source changes while copied
- **WHEN** a source file's device, inode, size, modification time, or change time differs after copying
- **THEN** preprocessing fails with `input_changed_during_copy` and removes the partial workspace

### Requirement: Build submission is idempotent

The system SHALL bind a caller-scoped idempotency key to the manifest digest and return the original job for an identical retry while rejecting reuse with different inputs.

#### Scenario: Client retries after losing the response
- **WHEN** the same authorized client resubmits the same key and manifest digest
- **THEN** the service returns the existing job and does not run a second build

### Requirement: Digital clipping is classified deterministically

The system SHALL inspect decoded PCM samples before normalization, SHALL NOT
equate a single 0 dBFS peak with proven clipping, and SHALL return a content-free
`pass`, `review`, or `reject` outcome using versioned builder-profile thresholds.
The default PCM16 policy SHALL review any exact full-scale sample and SHALL
reject either three consecutive samples within one least-significant bit of the
same-sign digital ceiling or a near-full-scale sample fraction of at least
0.001. Normalization SHALL NOT convert a rejected source into an accepted one.

#### Scenario: Isolated sample reaches 0 dBFS
- **WHEN** a valid PCM16 recording has an isolated full-scale sample but stays below the reject thresholds
- **THEN** the sample is marked `review` with safe metrics and is not automatically rejected or described as proven clipping

#### Scenario: Recording has a sustained flat top
- **WHEN** three or more consecutive PCM16 samples are within one least-significant bit of the same-sign digital ceiling
- **THEN** the sample is rejected with safe reason `audio_clipping_sustained`

#### Scenario: Recording has widespread near-ceiling samples
- **WHEN** at least 0.001 of decoded PCM16 samples are within one least-significant bit of either digital ceiling
- **THEN** the sample is rejected with safe reason `audio_clipping_ratio`

### Requirement: Build work is isolated from live inference

The system SHALL enforce measured resource and concurrency limits and prioritize live speech so offline builds do not breach the established TTS latency or error budget.

#### Scenario: Live speech approaches its resource threshold
- **WHEN** inference saturation or latency reaches the configured guardrail
- **THEN** new build work is delayed or paused while live synthesis continues

#### Scenario: Single-server GPU capacity is sufficient
- **WHEN** the existing Pea speech GPU has the configured free-VRAM reserve and live speech is healthy
- **THEN** one worker may run without requiring a second GPU server

### Requirement: Successful builds are immutable and reproducible

The system SHALL produce an immutable artifact and manifest recording digests and pinned builder/runtime/model/config versions, plus evaluation results and protected previews.

#### Scenario: Build completes
- **WHEN** preprocessing, construction, evaluation, and compatibility checks pass
- **THEN** the job succeeds with an immutable artifact digest and sufficient version metadata to reproduce or audit the build

### Requirement: Internal Pea activation requires supply-chain and admin evidence

The system SHALL bind every internally activated artifact to a digest-verified
SPDX SBOM covering the builder, runtime, models, and source voice-pack inputs,
and to an authenticated HeartCode admin attestation naming the exact artifact
and SBOM digests. The attestation SHALL confirm speaker authority, Pea-only
HeartCode use, no artifact redistribution, and explicit review of license
findings. Missing evidence, mismatched digests, incorrect scope, or non-approved
status SHALL fail closed. Local-ai SHALL verify this evidence but SHALL NOT
self-approve the admin decision.

#### Scenario: Internal activation lacks approved evidence
- **WHEN** an artifact has no SBOM or lacks an approved internal-Pea admin attestation for its exact artifact and SBOM digests
- **THEN** staging may retain the artifact for investigation but activation is rejected with a safe supply-chain reason

#### Scenario: Approved evidence matches exact digests
- **WHEN** the SPDX SBOM is available and its authenticated HeartCode admin attestation names the exact artifact and SBOM SHA-256 digests, confirms speaker authority and internal-only scope, and acknowledges its findings
- **THEN** the supply-chain gate passes and activation may proceed to compatibility and health checks

### Requirement: Artifacts pass clean compatibility validation

The system SHALL load internally produced artifacts in a restricted clean runner using the pinned Kokoro runtime and SHALL reject unsafe, malformed, non-finite, empty, or undecodable synthesis output.

#### Scenario: Artifact cannot load in pinned Kokoro
- **WHEN** the compatibility runner attempts to synthesize its fixed test phrases
- **THEN** the build fails compatibility and the artifact cannot enter the staging registry

### Requirement: Sensitive content is excluded from telemetry

The system SHALL NOT record raw audio, transcript text, access credentials, local filesystem paths, or protected preview identifiers in normal logs, traces, metrics, callbacks, or safe errors.

#### Scenario: Decoder crashes on a sample
- **WHEN** the worker records the failure
- **THEN** telemetry contains only opaque identifiers, phase, resource data, and a safe error code
