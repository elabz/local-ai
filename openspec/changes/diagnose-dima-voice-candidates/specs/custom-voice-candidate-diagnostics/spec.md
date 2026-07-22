## ADDED Requirements

### Requirement: Candidate inventory is explicit and integrity-bound

The system SHALL inventory only explicitly authorized custom-voice artifacts and
checkpoints, SHALL bind every entry to its digest and provenance, and SHALL load
tensors only through a restricted format-specific validation path. Candidates
without a completed construction result MAY be marked diagnostic-only but MUST
NOT become activation-eligible through the diagnostic workflow.

#### Scenario: Preserved timeout tensor is inventoried
- **WHEN** the timeout candidate has a matching recorded digest and passes restricted tensor validation
- **THEN** it is eligible for diagnostic comparison and remains ineligible for staging or activation

#### Scenario: Candidate identity or tensor validation fails
- **WHEN** a candidate is mutable, digest-mismatched, unsafe, malformed, empty, non-finite, or incompatible
- **THEN** it is excluded with a safe reason before any synthesis occurs

### Requirement: Diagnostic ranking uses a separate development set

The system SHALL require a digest-bound, authorized development set that is
disjoint from construction inputs and all release-held-out inputs. The system
MUST NOT use the four existing Dima release held-outs to rank candidates, tune
parameters, or select a checkpoint.

#### Scenario: Development inputs overlap protected release held-outs
- **WHEN** any development audio or transcript-sidecar identity matches an adaptation or release-held-out identity
- **THEN** the diagnostic fails closed before candidate evaluation

#### Scenario: No separate development set is available
- **WHEN** candidate inventory succeeds but no valid authorized development set exists
- **THEN** the system records an inventory-only inconclusive outcome and requests separate development recordings

### Requirement: Candidate comparison is reproducible and bounded

The system SHALL evaluate a bounded candidate set sequentially with the same
pinned Kokoro runtime, speaker encoder, ASR, text policy, and thresholds. It
SHALL preserve live-speech priority and configured resource limits and SHALL
record aggregate and per-sample content-free similarity, WER, minimum,
dispersion, compatibility, duration, and safe outcome evidence.

#### Scenario: Comparable candidates are evaluated
- **WHEN** two or more integrity-valid candidates and a valid development set are available
- **THEN** every candidate receives the same evaluation inputs and policy and the report records comparable content-free metrics

#### Scenario: Live speech needs capacity
- **WHEN** live inference reaches its configured activity, health, latency, or VRAM guardrail
- **THEN** diagnostic work pauses or stops without restarting live speech or changing its active voice mapping

### Requirement: Diagnostic outcomes cannot activate a voice

The system SHALL classify the comparison as `retain_active`,
`fresh_qualification_recommended`, `builder_redesign_recommended`, or
`inconclusive`. A diagnostic winner SHALL require a fresh release qualification
using untouched final held-outs and the existing supply-chain, approval, staging,
and activation gates.

#### Scenario: Existing candidate wins development comparison
- **WHEN** an existing candidate materially improves the fixed development metrics
- **THEN** the report recommends fresh qualification and makes no registry, provider, gateway, or HeartCode state change

#### Scenario: No candidate improves on v1
- **WHEN** no evaluated candidate provides a credible development improvement over active v1
- **THEN** the report recommends retaining v1 or redesigning the builder and no activation workflow begins
