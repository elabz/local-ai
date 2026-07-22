## 1. Rehydrate and Bound the Diagnostic

- [x] 1.1 Rehydrate the rejected Dima v2 construction, compatibility, evaluation, and active-v1 evidence without printing protected paths, transcripts, samples, credentials, or attestations.
- [x] 1.2 Confirm Pea speech health, active `custom-dima` v1 registry state, provider discovery, and authenticated stable-ID synthesis before diagnostic work.
- [x] 1.3 Define the bounded candidate classes and maximum trajectory sample: active v1, sealed final v2, preserved timeout candidate, and selected identity-valid atomic v2 checkpoints.
- [x] 1.4 Verify that diagnostic work requires no production service restart, compose mutation, active voice mount change, or registry transition.

## 2. Implement Restricted Candidate Inventory

- [ ] 2.1 Add a candidate inventory schema containing only opaque identity, digest, provenance, format, construction position, validation state, and diagnostic/release eligibility.
- [ ] 2.2 Implement no-follow regular-file, restrictive-mode, digest, and immutable provenance checks for completed artifacts and preserved candidates.
- [ ] 2.3 Implement format-specific restricted tensor validation using weights-only loading for artifacts and validated checkpoint-v2 decoding where applicable.
- [ ] 2.4 Classify legacy timeout candidates as diagnostic-only and reject mutable, mismatched, unsafe, malformed, empty, non-finite, or incompatible candidates before synthesis.
- [ ] 2.5 Add focused inventory tests for valid artifacts, legacy diagnostic-only candidates, checkpoint-v2 candidates, identity mismatch, unsafe serialization, and content-free failures.

## 3. Establish an Independent Development Set

- [x] 3.1 Determine whether separately authorized Dima development recordings already exist without exposing their content or private locations.
- [x] 3.2 If absent, stop comparative ranking with an inventory-only `inconclusive` outcome and document the minimum new recording request; do not substitute release held-outs.
- [ ] 3.3 If present, validate digest-bound authorization, audio/transcript pairs, restrictive storage, sample quality, and the configured minimum development count.
- [ ] 3.4 Prove development audio and transcript identities are disjoint from all adaptation inputs and the four prior release-held-out inputs.
- [ ] 3.5 Publish an immutable private development workspace and content-free validation evidence without changing existing build or release workspaces.

## 4. Implement the Bounded Comparison Harness

- [ ] 4.1 Extend the evaluator with an explicit development mode that accepts only a validated development manifest and cannot open release-held-out roles.
- [ ] 4.2 Pin the Kokoro runtime, speaker encoder, ASR, text policy, WER threshold, and similarity calculations identically across candidates.
- [ ] 4.3 Record per-sample content-free WER and similarity plus aggregate mean, minimum, dispersion, compatibility, duration, and safe outcomes.
- [ ] 4.4 Enforce sequential candidate execution, live-health/activity yielding, GPU admission/reserve, bounded CPU/memory/PIDs, read-only inputs, and no Docker socket.
- [ ] 4.5 Produce an atomic digest-bound comparison report with outcome `retain_active`, `fresh_qualification_recommended`, `builder_redesign_recommended`, or `inconclusive`.
- [ ] 4.6 Add focused tests proving equal inputs/policy across candidates, release-held-out rejection, deterministic aggregation/ranking, resource guardrails, safe telemetry, and no activation side effects.

## 5. Deploy and Run the Light-Touch Diagnostic

- [ ] 5.1 Build and pin the diagnostic image locally, run unit and integration tests, and validate image identity before copying or using it on Pea.
- [ ] 5.2 Deploy only the diagnostic tooling and immutable configuration to Pea without restarting or rebuilding live speech services.
- [ ] 5.3 Run the content-free candidate inventory and preserve exact inventory/report digests.
- [ ] 5.4 If an independent development set passed section 3, run candidates sequentially under live-service guardrails and preserve the immutable comparison report.
- [ ] 5.5 Confirm the diagnostic container is stopped, transient GPU resources are released, and live TTS remained healthy throughout.

## 6. Interpret and Close Out

- [ ] 6.1 Compare v1, final v2, timeout, and selected checkpoint evidence without treating construction fitness or prior release-held-out scores as development ranking evidence.
- [ ] 6.2 If an existing candidate wins credibly, recommend a new release qualification using fresh untouched final held-outs; do not stage or activate it.
- [ ] 6.3 If no candidate improves credibly, recommend retaining v1 and identify whether the evidence supports builder-objective redesign or additional recordings.
- [ ] 6.4 Verify `custom-dima` still resolves to active v1 through registry, provider discovery, authenticated gateway synthesis, and nontrivial audio.
- [ ] 6.5 Run focused tests and strict OpenSpec validation, then record content-free final status, report digests, limitations, and the next decision.
