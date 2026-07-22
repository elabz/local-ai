## ADDED Requirements

### Requirement: Optimized scoring preserves exhaustive search semantics

The builder SHALL preserve the configured fitness-text count, deterministic text order, candidate acceptance floor, hybrid score, and best-candidate selection of the pinned exhaustive sequential scorer. It MAY stop evaluating a candidate only after already observed results prove that remaining fitness texts cannot change that candidate's score or selection eligibility, and it SHALL evaluate every configured fitness text for any candidate that remains eligible.

#### Scenario: First fitness text rejects a candidate
- **WHEN** a candidate's first target similarity is at or below the deterministic acceptance floor and the aggregate is the minimum similarity
- **THEN** the builder records the same rejected score as exhaustive evaluation without synthesizing the remaining fitness texts

#### Scenario: Candidate remains eligible
- **WHEN** each observed fitness result remains above the deterministic acceptance floor
- **THEN** the builder evaluates every configured fitness text and calculates the same score and selection outcome as the exhaustive sequential scorer

#### Scenario: Optimization equivalence cannot be established
- **WHEN** a cached, short-circuit, or batch scoring backend fails its pinned correctness, determinism, numerical, or memory-reserve conformance checks
- **THEN** the builder uses the exhaustive sequential backend or fails with a safe reason and does not silently weaken the configured profile

### Requirement: Interrupted builds resume from identity-bound state

The builder SHALL atomically checkpoint sufficient versioned state to continue a deterministic search from its next uncompleted step, including the best candidate and score, progress and improvement counters, applicable random-generator states, active-work accounting, and exact build, input, builder, model, runtime, backend, and seed identities. It SHALL restore a checkpoint only after validating its schema, integrity, safe tensor content, bounds, and exact identity match.

#### Scenario: Compatible interrupted build resumes
- **WHEN** a job restarts with an intact checkpoint matching its exact manifest, plan, builder, model, runtime, backend, and seed identities
- **THEN** it resumes at the next uncompleted step without repeating completed search steps and produces the same outcome as the equivalent uninterrupted seeded build

#### Scenario: Checkpoint is corrupt or belongs to different inputs
- **WHEN** checkpoint integrity fails or any required identity or bound differs from the submitted job
- **THEN** resume fails closed with a content-free reason and the worker neither loads the candidate state nor silently starts over in the occupied output directory

#### Scenario: Legacy best-voice checkpoint is present
- **WHEN** an output directory contains a checkpoint that lacks the resumable schema and required search state
- **THEN** the worker classifies it as non-resumable and requires an explicit clean job rather than presenting it as a resumed build

### Requirement: Live-service pauses do not consume active build budget

Resumable build profiles SHALL account separately for active build work, time waiting for live-speech priority, and bounded wall lifetime. A live-service pause SHALL NOT consume the configured active-work budget, while the independent wall-lifetime limit SHALL prevent indefinite jobs.

#### Scenario: Build yields to a live call
- **WHEN** the live-inference guardrail pauses an offline voice build
- **THEN** live speech retains priority, pause duration is recorded without sensitive content, and the build's remaining active-work budget is unchanged

#### Scenario: Wall lifetime is exhausted
- **WHEN** repeated pauses or interruptions cause the configured maximum wall lifetime to expire
- **THEN** the worker checkpoints resumable state and exits with a safe bounded-lifetime outcome

### Requirement: Performance evidence excludes protected content

The builder SHALL expose bounded counters and timings sufficient to distinguish preprocessing, synthesis, speaker encoding, scoring, live-service waits, checkpointing, early rejection, backend fallback, and resume behavior. Such evidence SHALL NOT contain transcript text or hashes, audio, credentials, host paths, or protected preview identifiers.

#### Scenario: Operator diagnoses a slow build
- **WHEN** an authorized operator inspects build performance evidence
- **THEN** the evidence reports phase durations, safe resource observations, executed steps, generated fitness utterances, rejection counts, pause time, checkpoint sequence, and selected backend without exposing protected content

### Requirement: Adaptive stopping is explicit and reproducible

The builder SHALL run the profile's fixed step limit unless the digest-bound build plan explicitly selects a versioned adaptive-stop policy. An adaptive policy SHALL use construction data only, SHALL enforce configured minimum-step and no-improvement bounds, and SHALL record its parameters, executed steps, and stop reason in build metadata.

#### Scenario: Strict fixed-step profile runs
- **WHEN** a strict build plan specifies 6,000 steps and no adaptive-stop policy
- **THEN** performance optimizations do not reduce the step target and the build executes all steps unless it is cancelled or reaches a declared resource or lifetime boundary

#### Scenario: Versioned plateau policy is selected
- **WHEN** an authorized profile explicitly selects a plateau policy and the no-improvement window is reached after its minimum step
- **THEN** the build stops with a reproducible plateau reason and records the policy, parameters, and actual step count without consulting held-out samples
