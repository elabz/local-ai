## Context

The `kvoicewalk-multireference.v1` worker currently evaluates each generated candidate serially. Dima v2's strict profile evaluates 6,000 candidates against three adaptation transcripts, producing roughly 18,000 Kokoro utterances plus speaker embeddings. On Pea's dual-core 1.8 GHz CPU and P104-100 GPU, synthesis creates GPU bursts separated by Python, text-front-end, synchronization, and scoring work. The worker also yields to live inference, as required, but its wall-clock deadline continues to advance. Its checkpoint contains only the best voice tensor, so it cannot resume the search faithfully after interruption or timeout.

The builder must continue to isolate held-out samples, protect private content, yield to live speech, retain deterministic evidence, and default to the strict three-text/6,000-step profile. The Dima v2 job predates this change. It subsequently failed after writing only a legacy best-tensor checkpoint; that checkpoint must be preserved but cannot be resumed as deterministic search state.

## Goals / Non-Goals

**Goals:**

- Reduce unnecessary synthesis while preserving the sequential scorer's candidate acceptance and selection semantics.
- Reduce repeated candidate-independent text-front-end work.
- make interrupted builds resume deterministically from atomic, identity-bound checkpoints.
- Measure where active build time is spent without exposing audio, transcripts, paths, or protected identifiers.
- Evaluate batching and plateau stopping behind explicit versioned configuration and equivalence gates.
- Preserve live inference priority and configured VRAM reserves.

**Non-Goals:**

- Lowering Dima v2's three-text fitness setting, 6,000-step target, held-out threshold, or release criteria by default.
- Modifying the currently running build or treating its legacy tensor checkpoint as resumable state.
- Changing public speech APIs, HeartCode voice IDs, registry activation, or licensing/attestation policy.
- Moving builds to new hardware as part of this change.
- Parallel evaluation of independent candidates; each candidate depends on the current best and therefore changes search semantics if reordered.

## Decisions

### 1. Short-circuit only mathematically rejected candidates

The scorer will evaluate fitness texts in the profile-defined deterministic order. Because target similarity is the minimum across texts and hybrid scoring occurs only when that minimum exceeds `best_similarity * 0.98`, evaluation may stop as soon as any observed similarity is at or below that floor. The candidate then has the same zero score it would receive after all remaining texts. Passing candidates still receive every configured text and the same hybrid calculation.

This is preferred over reducing `fitness_text_count` or changing the threshold because it removes work only after the final outcome is already determined. Tests will compare short-circuit and exhaustive modes across passing, first-text rejection, later rejection, equality-boundary, NaN/error, and deterministic seeded search fixtures.

### 2. Cache candidate-independent text inputs within one worker

The worker will prepare each distinct fitness and stability text once through a supported Kokoro preprocessing boundary, then reuse immutable prepared inputs. Cache entries remain memory-local, are keyed by the pinned model/language/config and exact in-memory text identity, and are never logged or persisted. If the pinned Kokoro API cannot accept prepared input without bypassing supported behavior, this optimization remains disabled rather than patching private internals unsafely.

This is preferred over a persistent cache because transcripts are sensitive and build-local reuse provides the benefit without creating another protected data store.

### 3. Treat batching as an optional profiled backend

The sequential backend remains authoritative. A batch backend may combine the configured fitness texts for one candidate and batch speaker embeddings only if startup conformance fixtures demonstrate equivalent waveform validity, similarity decisions, hybrid score ordering, deterministic repeatability, and peak VRAM below the runtime reserve. Failure or unsupported APIs select the sequential path automatically and record only a safe backend/reason code.

Batching candidates across search steps is excluded because later candidates are generated from the best result so far. Mixed precision and `torch.compile` are also excluded initially: Pascal-class P104 hardware offers uncertain benefit, and numerical drift could change the search.

### 4. Introduce a versioned atomic checkpoint envelope

`custom-voice-checkpoint.v2` will contain:

- manifest and build-plan SHA-256 digests;
- builder profile/revision, worker image, Kokoro model/config/runtime identities, device/backend identity, and seed;
- next step, target step limit, improvement count, best voice tensor, best score components, and protected preview state needed to finish normally;
- Python, NumPy, Torch CPU, and applicable Torch CUDA random-generator states;
- cumulative active-compute time, live-pause time, checkpoint sequence, and creation timestamp;
- a schema/version marker and integrity digest over the serialized envelope.

Checkpoints will be written to a same-directory temporary file with restrictive permissions, flushed, atomically replaced, and directory-synced where supported. Resume validates all identity fields, tensor safety, bounds, and integrity before restoring state. A mismatch, corrupt checkpoint, completed result, or checkpoint from the legacy format fails with a safe reason and never silently starts a different search in the same output directory.

The deadline becomes an active-work budget for resumable profiles; time spent waiting on the live-inference guardrail is recorded separately and does not consume that budget. A separate bounded wall-lifetime guard prevents abandoned jobs from persisting indefinitely.

### 5. Keep adaptive stopping explicit and off by default

The strict profile continues to run its fixed step limit. A future/profile-selected plateau policy may stop after a configured minimum step and consecutive no-improvement window. Its policy name, parameters, stop reason, executed steps, and final quality evidence become reproducibility metadata. It cannot consult held-out samples or activate itself dynamically based on production pressure.

### 6. Add content-free performance evidence

Resource observations will record counters and durations for preprocessing, synthesis, speaker encoding, hybrid scoring, live-activity waits, checkpoint writes, candidates evaluated, fitness utterances generated, early rejections by ordinal position, backend fallback, resumes, and executed steps. Metrics use job-scoped opaque identifiers and bounded reason enums. They exclude transcript text or hashes, audio, host paths, preview identifiers, and credentials.

The initial rollout will benchmark exhaustive sequential scoring against optimized sequential scoring on an authorized synthetic/non-production fixture. Batching is enabled only if it passes correctness, determinism, VRAM, and measured wall-time gates.

## Risks / Trade-offs

- [Short-circuiting changes hidden random state inside synthesis] → Verify the pinned inference pipeline is deterministic and compare complete seeded walks; disable short-circuit mode if skipped synthesis affects later candidate generation.
- [Batch numerical differences alter rankings] → Keep sequential scoring authoritative and require conformance before opt-in; automatically fall back on mismatch or memory pressure.
- [Checkpoint deserialization expands the attack surface] → Accept only worker-created restricted files, use weights-only/safe data representations, validate schema and digests before tensors, and never resume foreign or legacy state.
- [Atomic checkpoints increase write cost] → Retain the bounded checkpoint interval and measure write duration; current checkpoint size is small relative to synthesis cost.
- [Active-time deadlines allow long wall-clock jobs during heavy live use] → Add a separate maximum wall lifetime while excluding deliberate live-service pauses from the compute budget.
- [Caching depends on unsupported Kokoro internals] → Implement only at a stable supported boundary; otherwise retain uncached operation and record the backend selection.
- [Performance metrics leak private material] → Restrict fields to numeric timings, counters, opaque job IDs, and enumerated reasons, with tests rejecting sensitive keys and values.

## Migration Plan

1. Confirm no worker using the current builder revision is still running. Preserve Dima v2's failed legacy checkpoint as non-resumable evidence before deploying the new image.
2. Add exhaustive scorer and checkpoint conformance fixtures, then implement safe metrics and the versioned build-plan fields with optimized modes disabled.
3. Enable semantics-preserving early rejection and build-local preprocessing cache after seeded equivalence tests pass.
4. Deploy resumable checkpoints for newly created jobs only. Legacy checkpoints remain explicitly non-resumable; operators may preserve them for diagnosis and start a new job with a new output directory.
5. Benchmark sequential and batch backends on Pea under live-speech guardrails. Enable batching only for profiles that pass all gates.
6. Keep plateau stopping disabled in the strict production profile until separately approved from collected convergence evidence.
7. Roll back by selecting the exhaustive sequential backend and disabling resume for new jobs; v2 checkpoint readers remain available long enough to finish already-started jobs.

## Open Questions

- Does the pinned Kokoro version expose a stable prepared-token or phoneme input boundary, or should the first release omit preprocessing caching?
- Can Resemblyzer batch embeddings without material numerical drift on the P104, and what batch size stays within the configured VRAM reserve?
- What bounded wall lifetime should accompany the active-work budget on a host that may prioritize live speech for extended periods?
- What convergence evidence would justify a plateau policy for a future builder profile?
