# Design: build-custom-kokoro-voices

## Context

Pea runs the pinned Kokoro-FastAPI speech provider behind the authenticated speech gateway. The upstream provider documents voice enumeration, synthesis, and weighted combinations that save `.pt` packs; it does not provide a sample-upload training API. Calling existing-voice blending “training” would not satisfy the requested custom-voice workflow.

This change introduces a separate voice-build subsystem whose output contract is a Kokoro-compatible voice pack. The builder is replaceable because the viable technique, its sample requirements, and its compute footprint must be measured rather than assumed. HeartCode remains the system of record for admin authorization and approval; local-ai is the system of record for job execution and artifact/serving state.

## Goals / Non-Goals

**Goals:**
- Establish whether an available sample-based technique produces acceptable Kokoro-compatible voices on current hardware.
- Provide an authenticated, idempotent, asynchronous build API for HeartCode.
- Validate and process exact audio/transcript pairs without exposing sensitive inputs publicly.
- Generate immutable artifacts, objective results, and standard previews for human review.
- Activate only an explicitly requested approved artifact, atomically and reversibly.
- Protect live TTS latency and availability from offline build workloads.

**Non-Goals:**
- Adding raw-upload or training endpoints to the public Kokoro/OpenAI-compatible API.
- Letting the build worker decide that a voice is authorized or approved for internal activation.
- Fine-tuning the Kokoro acoustic model unless the feasibility study selects and justifies it.
- Changing the accepted 40 kbps Opus live-delivery profile.
- Promising zero-shot cloning or a fixed minimum sample duration before measurement.

## Decisions

### Decision 1: Build the restricted pilot before deciding whether to release it

The first milestone implements and evaluates a pinned
`kvoicewalk-multireference.v1` pilot capable of producing artifacts the pinned
Kokoro version can load. A single authorized production speaker is sufficient
for this restricted pilot; a second speaker is required only before claiming
the profile generalizes as a service for arbitrary speakers. The benchmark
measures:

- artifact compatibility and repeatable loading;
- intelligibility via transcription error on held-out phrases;
- speaker similarity using a documented embedding metric plus blinded human review;
- naturalness/artifacts and multilingual or accent behavior where applicable;
- build duration, peak VRAM/RAM, disk use, and minimum useful sample quantity/quality;
- license, redistribution, and operational constraints of the builder and its models.

A candidate may be implemented, benchmarked, and produce protected previews
before it meets quality thresholds. Publication remains blocked unless the
artifact meets recorded thresholds, passes compatibility and operational
checks, and receives explicit human approval. If it fails, retain the evidence
and do not release it; implementation itself is not treated as a promise of
production quality.

The pilot computes one normalized speaker-embedding centroid from every
adaptation recording, uses deterministic seeds for multiple walks, scores
candidate tensors against that centroid, and reserves every held-out recording
for evaluation only. It is accurately described as style-tensor adaptation,
not Kokoro acoustic-model training.

### Decision 2: Separate control plane, workers, and online inference

The private control plane validates manifests, persists job state, and schedules work. Workers run decode/preprocessing/alignment/build/evaluation in isolated containers with explicit CPU, RAM, GPU, disk, concurrency, and timeout limits. They cannot mutate the active Kokoro voice directory.

Builds run on the existing speech GPU at concurrency one, in scheduled windows,
with enforced inference-priority admission based on measured free VRAM and live
speech health. The worker checkpoints accepted improvements and is terminated
or deferred when guardrails are crossed. Online TTS never waits for build
resources. Worker images and model revisions are pinned and recorded in every
result. A second GPU server is not required.

### Decision 3: Use a root-confined local intake and strict manifests

Source recordings and transcript sidecars are provisioned beneath a configured
private intake root on Pea. HeartCode submits only an opaque intake ID, expected
manifest digest, stable voice/version/build IDs, idempotency key, and builder
profile. The service reads `<intake-root>/<intake-id>/manifest.json`; the
manifest names samples by opaque ID and root-relative audio/transcript paths and
records checksums, decoded metadata, language, and authorization/provenance ID.
No request may supply an absolute host path, URL, or `file://` URI.

Intake IDs and relative paths use strict allow-listed grammars. Resolution must
remain beneath the configured root and reject dot segments, separators in IDs,
symlinks, hard-linked files outside policy, devices/FIFOs/sockets, unexpected
ownership or mode, and files that change between validation and copy. Workers
open regular files without following links, enforce quotas, verify manifest and
file digests, and copy accepted inputs into a per-job workspace with restrictive
permissions before decoding. The intake tree is read-only to workers and is
never the active Kokoro voice directory.

Generated packs, manifests, reports, and previews use separate configured local
artifact roots. API results expose opaque artifact/preview IDs, never host
paths. Protected preview reads are authenticated and stream a digest-verified
file from the private preview root. Raw content, transcripts, credentials, and
local paths are never logged or added to metrics. Build services need no network
egress for source ingestion.

### Decision 4: Make jobs durable, idempotent, and observable

Job states are `queued`, `validating`, `preprocessing`, `building`, `evaluating`, `succeeded`, `failed`, `cancelling`, `cancelled`, and `deleting`. The same caller/idempotency key and manifest digest returns the original job; reusing a key for different inputs is rejected.

Results include safe validation findings, quality metrics and thresholds, opaque preview IDs, builder/runtime versions, artifact digest/size, and timestamps. Authenticated callbacks are best-effort; status polling is authoritative. Cancellation is cooperative and never leaves a partial artifact eligible for staging.

### Decision 5: Treat artifacts as immutable supply-chain objects

A successful build writes a content-addressed or otherwise immutable voice pack and manifest containing the builder image/model revisions and source/build digests. Before staging, a clean compatibility runner loads the pack using the pinned Kokoro runtime, synthesizes fixed phrases, and validates non-empty, finite, decodable output.

Artifacts are never deserialized from an untrusted client upload. Because PyTorch pickle-capable formats can execute code, only internally produced artifacts that match the recorded digest enter the registry; loading runs with the safest supported serialization path and restricted permissions/container boundary.

### Decision 6: Stage, then atomically activate an exact digest

The registry maps a stable voice ID to immutable versions and has separate `staged`, `active`, `retired`, and `deleted` state. HeartCode may stage a successful version for preview, but activation requires a distinct authenticated request naming the exact version and digest.

Activation installs the pack into a versioned location, makes it discoverable to Kokoro through the supported loader/reload mechanism, runs a synthesis health probe, and atomically switches the stable ID. If load or health fails, the old active mapping remains. Rollback performs the same atomic switch to a prior healthy version.

The implementation must test whether the pinned provider safely reloads voice packs at runtime. If it does not, use a controlled blue/green provider restart or equivalent drained replacement instead of mutating a live mount and hoping it reloads.

### Decision 7: Keep public inference compatibility narrow

Only active registry entries are visible through voice discovery and accepted by `/v1/audio/speech`. Draft job APIs, local intake management, evaluation previews, manifests, and registry mutations are private control-plane operations and are not routed through LiteLLM or the user-facing speech gateway.

Built-in voices remain unchanged. Stable custom IDs use a reserved validated namespace to avoid collisions and path traversal. TTS response formats, streaming behavior, and the `opus-40k` profile remain unchanged.

### Decision 8: Reconcile and garbage-collect conservatively

Registry state records artifact digests and loaded-provider state. Periodic reconciliation detects missing, unexpected, or mismatched packs and marks affected voices unhealthy rather than serving an unknown artifact. Metrics contain counts, state, duration, resource use, and safe error codes only.

Retirement prevents future activation/selection but retains rollback artifacts according to policy. Deletion is asynchronous, reference-aware, and verified across job workspaces, raw cached inputs, previews, staged/active packs, and backups. An active or rollback-referenced artifact cannot be garbage-collected until explicitly detached.

### Decision 9: Separate peak contact from demonstrated digital clipping

Clipping analysis runs on decoded source PCM before resampling, gain changes, or
normalization. Merely reaching 0 dBFS is a review signal, not proof of damaged
audio. The versioned default PCM16 policy rejects stronger objective evidence:
three consecutive samples within one least-significant bit of the same-sign
ceiling, or a near-ceiling fraction of at least 0.001. Reports contain only the
opaque sample ID, numeric metrics, outcome, policy version, and safe reason
codes. A review outcome requires the authorized human quality step before a
production build; a reject outcome requires a clean source or retake and cannot
be repaired into acceptance by normalization.

### Decision 10: Fail internal activation closed on exact supply-chain and admin evidence

Every internally activated version carries an SPDX JSON SBOM and a separate
HeartCode admin attestation. Both are immutable inputs to activation. The SBOM
exposes package/model/voice-pack license findings, including unresolved items,
for explicit review. The attestation confirms speaker authority, Pea-only
HeartCode use, no artifact redistribution, reviewed findings, and binds the
decision to the exact artifact and SBOM SHA-256 digests. Local-ai generates and
verifies technical evidence but cannot approve its own output. Rebuilding either
object requires a new authenticated admin attestation.

## Private API Contract

The versioned internal API provides:

- create a build from an opaque local intake ID, expected manifest digest, and idempotency key;
- read job state, safe events, evaluation results, and protected preview references;
- cancel/retry where the state permits;
- stage an internally generated artifact version;
- activate an exact stable voice ID/version/digest, with health result;
- list/reconcile registry entries, roll back, retire, and request verified deletion.

Authentication uses a dedicated scoped service credential distinct from end-user and general inference keys. Requests and callbacks are signed or mutually authenticated, rate limited, timestamped, and protected against replay. Authorization differentiates build, preview-read, activate, and delete scopes.

## Risks / Trade-offs

- **No compatible builder meets quality:** record a no-go and evaluate a different TTS/cloning architecture; do not counterfeit success with voice blending.
- **Consent/impersonation abuse:** accept jobs only from the private HeartCode admin service; retain source authorization IDs and audit events; local-ai never self-publishes.
- **Malicious local inputs or artifacts:** root confinement, no-follow regular-file opens, ownership/mode checks, isolated decoding, quotas, internally generated checksummed packs, and restricted loading.
- **GPU starvation:** benchmark, queue, cap concurrency, prioritize inference, and stop builds when live latency/error budgets are exceeded.
- **Provider reload behavior:** prove it under concurrency; otherwise use blue/green replacement.
- **Cross-repo drift:** contract tests and version negotiation; unknown manifest or artifact versions fail closed.
- **Storage growth:** retention classes, quotas, reference-aware garbage collection, and alerts.

## Migration Plan

1. Run and document the feasibility/security/license benchmark without production registry changes.
2. Implement the private control plane and worker with non-production local intake/artifact roots and contract tests.
3. Build authorized test voices; exercise validation, cancellation, failure, cleanup, and compatibility tests.
4. Implement staging and blue/green or reload-based activation; test concurrency, atomic rollback, and serving latency.
5. Integrate HeartCode in review-only mode, then enable one internal Pea activation behind feature flags.
6. Enable curated production builds after operational, privacy, and incident-response review.

## Open Questions

- Which candidate builder and license satisfy the feasibility gate?
- Does the pinned Kokoro-FastAPI version support a safe runtime refresh of newly installed packs, or is blue/green provider replacement required?
- Which GPU and scheduling window provide adequate isolation on Pea after measurement?
- What Pea filesystem or encrypted volume will back the configured intake, workspace, artifact, preview, and backup roots, and what are their approved retention periods?
- What quantitative thresholds, together with human review, define an acceptable voice?
