# Custom Voice Threat Model

Review date: 2026-07-17. Scope: private intake, preprocessing, build and
evaluation workers, artifact storage, future control plane, registry,
activation, callbacks, and deletion.

## Assets and trust boundaries

Protected assets are source recordings, exact transcripts, authorization
references, generated voice tensors, previews, service credentials, legal
attestations, and registry mappings. HeartCode is authoritative for consent and
publication approval. Local-ai is authoritative for execution and serving
state. The private control plane, read-only intake, isolated workers, immutable
artifact store, compatibility runner, and online Kokoro provider are separate
trust boundaries. LiteLLM and public speech credentials are outside the build
authorization boundary.

## Threats and controls

| Area | Threat | Required control and current disposition |
|---|---|---|
| Local intake | Absolute paths, traversal, symlinks, devices, FIFOs, sockets, or hard links escape the authorized root. | Strict opaque IDs and relative components; descriptor-relative `O_NOFOLLOW` opens; regular-file, link-count, owner, and mode checks. Implemented and tested. |
| TOCTOU | A validated source is exchanged or modified while copied. | Copy from the validated descriptor, compare device/inode/size/mtime/ctime before and after, enforce the manifest digest, and atomically publish only a complete workspace. Implemented and tested. |
| Resource abuse | Oversized files, transcripts, duration, sample counts, or decode bombs exhaust disk/RAM/CPU. | Byte/transcript quotas, exact profile counts, measured PCM metadata and duration bounds, decoder timeout, private temporary workspace cleanup. Implemented for the selected PCM16 profile; service-level job timeout/cancellation remains required. |
| Transcript/content injection | Transcript content reaches commands, logs, callbacks, paths, or metrics. | Transcripts are UTF-8 data files only and are never interpolated into a shell command, identifier, log, callback, or metric. Telemetry verification remains a dedicated task. |
| Decoder compromise | Crafted media exploits `ffmpeg` or an audio library. | Decode in the pinned unprivileged worker image with read-only intake, private output mount, no host control socket, no public route, timeout and quotas. Production deployment must add explicit seccomp/capability and CPU/RAM limits. |
| Artifact deserialization | A malicious PyTorch pickle executes code. | Accept only internally produced digest-bound files; clean runner uses `torch.load(..., weights_only=True)` and validates tensor type, dtype, shape, finiteness, and synthesis output. Implemented and tested. |
| Artifact substitution | Pack bytes differ between build, review, stage, and activation. | SHA-256 and size binding, content-addressed immutable copy, build-result provenance, exact-digest compatibility and activation gates. Implemented foundations; registry integration remains required. |
| Service authorization | Public inference keys invoke builds, previews, activation, or deletion. | Separate private endpoint and scoped build/read/activate/delete credentials; no LiteLLM route. Control-plane service remains required and must fail before opening intake. |
| Replay/idempotency | Replayed create, callback, activation, or deletion mutates state twice. | Caller-scoped idempotency binding, signed timestamps/nonces, replay cache, durable monotonic events, and exact expected state/version. Contract exists; durable service implementation remains required. |
| Callback forgery/leakage | Forged callbacks advance HeartCode or disclose protected data. | Signed callbacks over a configured allow-listed destination, bounded retries, no redirects, content-free payloads, and authoritative polling. Implementation remains required. |
| Registry mutation | Path injection, built-in collision, stale writes, or partial activation publishes the wrong voice. | Reserved `custom-` ID grammar, immutable versions, digest compare-and-switch, clean health probe, preserve prior mapping on failure. Atomic switch foundation is implemented; blue/green provider integration remains required. |
| GPU denial of service | Offline work starves or crashes live STT/TTS. | Concurrency one, initial 5,000 MiB admission, continuous 1,024 MiB free-VRAM floor, checkpoints, offline dependencies, dedicated GPU placement, and live-health monitoring. Pilot measurement is in progress; timeout/preemption integration remains required. |
| Impersonation misuse | An artifact is created or activated without valid speaker authority. | Digest-bound authorization reference, private HeartCode admin caller, exact-digest internal-Pea attestation, protected preview, and explicit exact-version activation. Local-ai never invents consent or self-approves activation. |
| Preview disclosure | Review audio becomes publicly enumerable or leaks through telemetry. | Random/derived opaque preview IDs, `0700` root/`0600` files, authenticated read scope, no public discovery, and no preview IDs in normal telemetry. Protected preview endpoint remains required. |
| Deletion abuse | Active, rollback, or evidentiary material is erased, or sensitive remnants persist. | Asynchronous reference-aware deletion with state checks, retention holds, inventory of workspace/cache/preview/artifact/backup references, verified removal, and an audit event. Implementation remains required. |
| Supply chain | Mutable images/models, network downloads, unresolved licenses, or forged approval enter production. | Exact image/revision pins, offline worker, SPDX validation, and external attestation bound to artifact and SBOM digests. Implemented foundations; exact production SBOM and external approval remain release blockers. |

## Logging and safe failures

Normal telemetry may contain opaque job/sample IDs, phase, duration, bounded
resource values, state, and allow-listed reason codes. It must not contain raw
audio, transcript text, credentials, host paths, signed callback material, or
protected preview IDs. Exceptions crossing a service boundary are mapped to
safe codes; detailed worker output remains in access-controlled operational
storage with retention limits.

Implementation verification now covers each normal telemetry surface: worker
third-party stdout/stderr is contained; API validation and domain failures map
to content-free reason codes; callback schemas allow only job/event/state/time
fields; Prometheus labels are fixed phase/state/reason enums and never caller,
intake, artifact, transcript, path, credential, or preview values. The private
service is deployed with framework access logging disabled because protected
preview IDs occur in request paths. Access-controlled incident diagnostics are
not normal telemetry and follow the retention policy above.

## Residual risk and release posture

KVoiceWalk is style-tensor adaptation and can produce recognizable but
unacceptable or misleading speech. Objective metrics do not establish consent,
naturalness, or fitness for publication. The restricted benchmark may run, but
release remains closed until compatibility, held-out evaluation, live-service
impact, SBOM/legal evidence, protected review, and explicit human approval all
bind to the exact artifact digest. A failed gate records a no-release outcome;
normalization, blending, or operator discretion cannot silently bypass it.
