## 1. Baseline and Safety Fixtures

- [ ] 1.1 Capture a content-free baseline benchmark for exhaustive sequential scoring on the pinned Pea-class hardware profile, including phase timing, GPU utilization, generated utterance count, and peak VRAM.
- [x] 1.2 Add deterministic scorer fixtures covering passing candidates, rejection at each fitness-text position, equality at the acceptance floor, non-finite/error handling, and best-candidate ties.
- [x] 1.3 Add an uninterrupted seeded-walk fixture that records authoritative exhaustive final voice, score, improvement count, and random-state progression.
- [x] 1.4 Verify the Dima v2 worker is no longer running and preserve its failed legacy checkpoint as non-resumable evidence before deploying or starting any worker built from this change.

## 2. Safe Performance Observability

- [x] 2.1 Extend resource observations with bounded phase durations and counters for preprocessing, synthesis, speaker encoding, hybrid scoring, live waits, checkpoint writes, candidates, utterances, rejection position, backend fallback, resumes, and executed steps.
- [x] 2.2 Add telemetry schema tests that reject transcript text or hashes, audio, credentials, host paths, and protected preview identifiers.
- [x] 2.3 Emit safe periodic progress evidence that lets operators estimate throughput and completion without inspecting private worker content.

## 3. Semantics-Preserving Candidate Evaluation

- [x] 3.1 Refactor exhaustive scoring behind an explicit sequential scoring backend without changing existing results.
- [x] 3.2 Implement deterministic early rejection when an observed minimum target similarity is at or below the candidate acceptance floor.
- [x] 3.3 Ensure eligible candidates still evaluate all configured fitness texts and retain the authoritative hybrid calculation.
- [x] 3.4 Prove scorer-level and complete seeded-walk equivalence between exhaustive and early-rejection modes, including generated-utterance savings.
- [x] 3.5 Add a safe runtime fallback or failure path when deterministic equivalence cannot be established.

## 4. Build-Local Text Preprocessing Cache

- [x] 4.1 Identify and test a supported pinned-Kokoro boundary for reusing candidate-independent prepared fitness and stability text inputs.
- [x] 4.2 Implement a memory-only, build-scoped immutable prepared-input cache without logging or persisting text-derived values.
- [x] 4.3 Add equivalence, lifecycle, and sensitive-data tests for cached and uncached synthesis.
- [x] 4.4 Retain uncached sequential operation and a safe backend reason when the pinned runtime does not support prepared inputs.

## 5. Atomic Resumable Checkpoints

- [x] 5.1 Define and validate the `custom-voice-checkpoint.v2` envelope, identity fields, progress bounds, safe tensor representation, integrity digest, and restrictive permissions.
- [x] 5.2 Capture and restore the best candidate and score, next step, improvement count, protected preview state, Python/NumPy/Torch CPU/Torch CUDA RNG states, and active/pause accounting.
- [x] 5.3 Implement same-directory temporary checkpoint writes, flush, atomic replacement, and directory sync with crash-injection tests.
- [x] 5.4 Validate exact manifest, plan, builder, image, model, runtime, backend, device, and seed identities before loading resumable state.
- [x] 5.5 Fail closed with content-free reasons for corrupt, unsafe, mismatched, out-of-bounds, completed-result, and legacy checkpoints without silently restarting in an occupied output directory.
- [x] 5.6 Demonstrate that interruption at multiple checkpoint boundaries resumes at the next step and matches the uninterrupted seeded-walk outcome.

## 6. Active and Wall-Time Budgets

- [x] 6.1 Add versioned build-plan fields for active-work budget and independent maximum wall lifetime with backward-compatible validation defaults.
- [x] 6.2 Exclude measured live-inference guardrail waits from active-work consumption while retaining cancellation, health, VRAM, and wall-lifetime enforcement.
- [x] 6.3 Checkpoint and exit safely when wall lifetime expires, and test repeated live-pause/resume accounting.

## 7. Compatibility-Gated Batching

- [x] 7.1 Prototype within-candidate synthesis and embedding batch gating without parallelizing dependent candidate steps.
- [x] 7.2 Add startup conformance checks for waveform validity, score decisions and ordering, repeatability, and peak VRAM reserve.
- [x] 7.3 Select the batch backend only when it passes correctness and measured performance gates; otherwise select sequential mode with a safe reason.
- [ ] 7.4 Benchmark batch sizes on the P104-100 and document whether batching is enabled for the production builder profile.

## 8. Explicit Adaptive Stop Policy

- [x] 8.1 Add optional versioned plateau-policy validation with minimum-step and consecutive-no-improvement bounds, disabled by default.
- [x] 8.2 Record selected policy, parameters, executed steps, and stop reason in reproducibility metadata without accessing held-out samples.
- [x] 8.3 Add tests proving the strict three-text/6,000-step profile does not stop on a plateau when no adaptive policy is selected.

## 9. Integration and Rollout

- [x] 9.1 Run focused unit, security, deterministic equivalence, checkpoint fault-injection, and end-to-end custom-voice build tests.
- [x] 9.2 Build the pinned worker image and run a clean preflight plus interrupted/resumed build against non-production authorized fixtures.
- [x] 9.3 Compare optimized and baseline wall time, active time, generated utterances, peak VRAM, final outcome, and live-TTS latency/error evidence.
- [x] 9.4 Deploy with exhaustive sequential fallback available, verify live speech remains healthy, and document rollback and legacy-checkpoint handling.
- [x] 9.5 Keep adaptive stopping disabled and batching gated until their recorded Pea benchmarks independently satisfy the approved correctness, resource, and performance criteria.
