## Why

Strict custom Kokoro voice builds currently perform thousands of sequential, repeated synthesis and speaker-scoring operations, leaving the assigned GPU intermittently idle and risking loss of hours of work at the build deadline. The builder needs semantics-preserving performance improvements and resumable progress so strict multi-reference searches complete reliably on Pea's existing hardware without weakening quality gates or disrupting live speech.

## What Changes

- Short-circuit candidate evaluation once an evaluated fitness text proves that the candidate cannot exceed the current acceptance floor, while preserving the exact score and selection outcome of a complete evaluation.
- Cache deterministic, candidate-independent fitness-text preprocessing and reuse it within a build.
- Add an optional, compatibility-gated batch path for synthesis and speaker-embedding scoring, with an automatically selected equivalent sequential fallback.
- Replace best-voice-only checkpoints with atomic, versioned resumable state containing the completed step, best candidate and score, improvement count, random-generator state, and compatibility metadata.
- Resume an interrupted build only when its checkpoint matches the exact manifest, build plan, builder revision, model/runtime identity, and seed; otherwise fail closed without silently restarting or mixing state.
- Add safe phase timing, candidate rejection, GPU duty-cycle, pause, checkpoint, and resume metrics without recording transcripts, audio, paths, or protected identifiers.
- Support measured plateau stopping as an explicit, versioned policy, disabled for strict fixed-step profiles unless separately configured and recorded.
- Preserve live-speech priority, VRAM reserves, held-out isolation, deterministic metadata, strict three-text fitness, and the 6,000-step target by default.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `custom-kokoro-voice-builds`: Require outcome-equivalent optimized candidate scoring, compatible resumable checkpoints, safe performance observability, and explicit recording of any early-stop policy.

## Impact

- Affects the private custom-voice worker, build-plan validation, checkpoint schema and lifecycle, worker launcher, resource observations, and focused tests under `gpu-server/custom_voice`.
- May use additional Kokoro or speaker-encoder batching APIs only after equivalence and memory-reserve validation; no public API or active voice identifier changes are required.
- Existing legacy checkpoints remain non-resumable and must be rejected safely or handled by an explicit clean restart.
- The failed Dima v2 build and its legacy checkpoint are preserved as non-resumable evidence; implementation does not modify or reinterpret that tensor as resumable state.
