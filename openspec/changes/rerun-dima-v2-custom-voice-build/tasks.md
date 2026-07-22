## 1. Rehydrate and Preserve Failed Attempt

- [x] 1.1 Read this change's proposal, design, specification, and task list after the session cache is cleared.
- [x] 1.2 Verify Pea connectivity and confirm `pea-speech-tts` is running and model-health is healthy without printing secrets or unrestricted inspection output.
- [x] 1.3 Confirm `bench-speaker-001-dima-v2-seed-137` is stopped with safe reason `worker_timeout`, its final checkpoint is present, and `result.json` and `artifact.pt` are absent.
- [x] 1.4 Record safe checkpoint size, modification time, SHA-256 digest, r3 image identity, and failure-log evidence without moving, deleting, or treating the checkpoint as resumable.
- [x] 1.5 Confirm Dima v1 remains active, discoverable, and selectable through its existing stable HeartCode voice identity.

## 2. Prepare Isolated Rerun

- [ ] 2.1 Create job identity `bench-speaker-001-dima-v2-seed-137-rerun-1` with distinct workspace, result, launch-log, lock, container, and idempotency identities.
- [ ] 2.2 Verify the rerun destinations do not already exist; fail closed rather than deleting or overwriting unexpected state.
- [ ] 2.3 Recreate the digest-bound build plan with seed 137, `adapt-002` through `adapt-006`, explicit `adapt-001` exclusion, population 10, three fitness texts, checkpoint interval 100, 6,000 steps, and `max_duration_seconds=36000`.
- [ ] 2.4 Verify the four held-out samples remain declared only for postbuild evaluation and are absent from all construction references.
- [ ] 2.5 Validate exact manifest, input, transcript-sidecar, plan, builder revision, Kokoro runtime/model/config, and worker-image digests without printing private content.
- [ ] 2.6 Set restrictive ownership and permissions on the new private workspace and result locations.

## 3. Named Worker Preflight

- [ ] 3.1 Confirm adequate host disk space, no conflicting custom-voice worker, and no active build lock.
- [ ] 3.2 Confirm the pinned `local-ai-custom-voice-worker:dima-v2-r3` image and recorded image digest are available; do not substitute an unpinned image.
- [ ] 3.3 Confirm local pinned Kokoro configuration and model weights load without network access.
- [ ] 3.4 Verify the intended NVIDIA GPU is healthy, the worker receives the NVIDIA runtime/device, and admission plus runtime free-VRAM reserves pass.
- [ ] 3.5 Run a named short synthesis/embedding preflight using authorized build data and report only success, duration, frame count, resource bounds, and safe error codes.
- [ ] 3.6 Recheck TTS model health immediately before launch and stop if the production guardrail is not satisfied.

## 4. Launch and Durable Watch

- [ ] 4.1 Launch exactly one detached rerun worker under the new identity with live-health/activity yielding, cancellation, and resource guardrails enabled.
- [ ] 4.2 Verify the worker is running, using the expected pinned image and GPU, consuming bounded resources, and has not modified the failed attempt.
- [ ] 4.3 Start a persistent restricted watch on Pea that records UTC time, worker state, checkpoint freshness, bounded CPU/memory activity, result/artifact presence, safe terminal reason, and TTS health.
- [ ] 4.4 Document the safe reconnect/status command in the change or project operations memory so a fresh session can inspect the existing watch without launching a duplicate.
- [ ] 4.5 Track checkpoint freshness and TTS health through terminal completion while avoiding restarts based only on temporary low utilization.

## 5. Validate Construction Result

- [ ] 5.1 On worker exit, distinguish successful result production from timeout, cancellation, GPU failure, health failure, or other safe terminal reason.
- [ ] 5.2 For success, validate `result.json` schema and its exact manifest, plan, seed, builder, image, model/runtime identities, 6,000 executed steps, finite metrics, duration, and artifact digest.
- [ ] 5.3 Load the produced tensor through the restricted weights-only validation path and reject unsafe, malformed, empty, non-finite, or incompatible content.
- [ ] 5.4 Preserve the completed construction evidence immutably before beginning postbuild qualification.
- [ ] 5.5 For failure, leave Dima v1 active, preserve rerun evidence, record the safe reason, and do not automatically begin another rerun.

## 6. Strict Postbuild Qualification

- [ ] 6.1 Run the clean pinned Kokoro compatibility runner and require valid nontrivial synthesis output for every compatibility phrase.
- [ ] 6.2 Evaluate only the four untouched held-out recordings with the existing WER policy and strict minimum mean speaker similarity `0.68`.
- [ ] 6.3 Record per-sample content-free metrics and the aggregate `pass`, `review`, or `reject` decision without relaxing thresholds after observing results.
- [ ] 6.4 Compare safe aggregate v2 evidence with v1's prior mean similarity of approximately `0.6417` while avoiding unsupported claims from construction fitness alone.
- [ ] 6.5 If qualification passes, seal the immutable `custom-dima` v2 artifact and generate its exact manifest, protected preview, SPDX SBOM, and digest-bound evidence.

## 7. HeartCode Review and Activation

- [ ] 7.1 Make the qualified v2 candidate and protected preview available to the HeartCode admin review workflow without exposing it publicly.
- [ ] 7.2 Obtain authenticated internal Pea-only admin approval naming the exact artifact and SBOM digests, speaker authority, no-redistribution scope, and reviewed findings.
- [ ] 7.3 Stage v2 and verify registry version/digest plus provider discovery before activation; do not alter v1 on staging failure.
- [ ] 7.4 Activate v2 only after all gates pass, then verify provider synthesis, stable-ID gateway mapping, HTTP success, nontrivial audio bytes/format, HeartCode catalog, preview, Quick Chat, character chat, and voice-call paths.
- [ ] 7.5 Confirm v1 is retired only by the successful v2 activation transition and that `custom-dima` resolves everywhere to the exact v2 digest.

## 8. Closeout

- [ ] 8.1 Stop the persistent watch after a recorded terminal outcome and retain only the restricted evidence required for audit and troubleshooting.
- [ ] 8.2 Run focused runtime, custom-voice, and OpenSpec validation and reconcile every task with evidence.
- [ ] 8.3 Record final status, artifact/evaluation identifiers, active version, and any follow-up work without including private samples, transcripts, paths, or credentials.
