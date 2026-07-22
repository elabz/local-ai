# Tasks: build-custom-kokoro-voices

## 1. Feasibility and threat model

- [x] 1.1 Inventory the pinned Kokoro-FastAPI voice-pack loader, discovery, reload behavior, serialization safety, naming constraints, and exact artifact contract
- [x] 1.2 Identify licensed sample-to-Kokoro voice-building candidates; document whether each performs embedding extraction, adaptation, fine-tuning, or another process
- [x] 1.3 Benchmark the restricted pilot on the authorized production speaker for compatibility, held-out intelligibility, speaker similarity, human naturalness, sample requirements, build time, VRAM/RAM, disk, and live-TTS interference; require a second speaker only before general-purpose rollout
- [x] 1.4 Record pass/fail thresholds, licensing findings, selected builder/profile, capacity placement, and a no-go outcome if none qualifies
- [x] 1.5 Threat-model local intake provisioning, transcripts, path traversal/symlink/TOCTOU attacks, decoders, PyTorch artifacts, service auth, callbacks, registry mutation, deletion, and impersonation misuse

## 2. Contract and durable control plane

- [x] 2.1 Finalize a versioned contract with HeartCode `add-admin-custom-voices`: opaque local intake ID plus manifest digest, strict manifest, idempotency, states, safe errors, metrics/results, artifact identity, callbacks, activation, rollback, and deletion
- [x] 2.2 Add a private authenticated control-plane service with separate build/read/activate/delete scopes, replay protection, rate limits, and no LiteLLM/public route
- [x] 2.3 Add durable job/event/registry storage and queue recovery; enforce idempotency key plus manifest digest semantics
- [x] 2.4 Implement status polling and signed callbacks with retries; add contract and forward/backward-version tests

## 3. Secure input and preprocessing

- [x] 3.1 Implement root-confined local intake, strict IDs/relative paths, no-follow regular-file opens, ownership/mode checks, checksum verification, quotas, workspace isolation, restrictive permissions, and change-during-copy protection
- [x] 3.2 Validate/decode configured formats and enforce measured duration/count/size/language/transcript requirements from the selected builder profile
- [x] 3.3a Specify and implement deterministic pre-normalization PCM16 clipping classification with pass/review/reject outcomes, safe metrics, and tests
- [x] 3.3b Implement deterministic 24 kHz PCM normalization, channel/rate conversion, silence/level checks, transcript-rate plausibility, and safe per-sample findings
- [x] 3.3c Implement ASR-grade transcript alignment and segmentation where the selected profile requires them
- [x] 3.4 Verify logs, traces, metrics, callbacks, and errors contain no raw audio, transcript content, credentials, local paths, or protected preview identifiers
- [x] 3.5 Implement cancellation and cleanup for partial downloads, decode failures, timeouts, worker crashes, and restarts

## 4. Voice build and evaluation worker

- [x] 4.1 Build a pinned isolated `kvoicewalk-multireference.v1` pilot worker; use every adaptation recording, exclude held-outs, and record code/image/model/config/input revisions and random seed in every result
- [x] 4.2 Enforce resource, concurrency, timeout, and inference-priority limits based on the feasibility benchmark
- [x] 4.3 Produce an immutable artifact and manifest with digest, size, compatibility version, and provenance reference
- [x] 4.4 Generate fixed held-out previews and compute selected intelligibility, similarity, artifact, and performance metrics with threshold outcomes
- [x] 4.5a Implement the digest-bound clean pinned Kokoro compatibility runner and unit-test its fail-closed artifact/audio validation
- [x] 4.5b Run selected-builder artifacts through the compatibility container on the production GPU and record results
- [x] 4.6 Add deterministic/repeatability, malformed input, resource exhaustion, crash recovery, and malicious artifact/input tests
- [x] 4.7 Specify and implement a fail-closed SPDX SBOM and exact-digest HeartCode admin-attestation gate for internal Pea activation with tests

## 5. Versioned registry and serving integration

- [x] 5.1 Add reserved stable voice IDs, immutable versions, digests, and staged/active/retired/deleted/unhealthy registry states
- [x] 5.2 Implement protected preview access and staging without exposing the voice through public discovery
- [x] 5.3 Prove runtime pack refresh under concurrent synthesis; implement safe reload or drained blue/green provider replacement based on the result
- [x] 5.4a Implement and unit-test the exact-digest, health-probed atomic registry switch that preserves the prior mapping on failure
- [x] 5.4b Integrate the atomic switch with blue/green Kokoro provider activation and production discovery
- [x] 5.5 Implement rollback, retirement, reconciliation, and health reporting; only healthy active voices appear in discovery and synthesis
- [x] 5.6 Add reference-aware asynchronous deletion/garbage collection with verification and safeguards for active/rollback artifacts

## 6. Operations and end-to-end validation

- [x] 6.1 Add content-free metrics/alerts for queue depth, job phase/duration/failure, resource saturation, registry drift, activation health, and cleanup backlog
- [x] 6.2 Document build worker deployment, secrets/scopes, storage/backup/retention, capacity controls, incident response, activation, rollback, and disaster recovery
- [x] 6.3 Run an authorized HeartCode build through validation, preprocessing, build, evaluation, protected preview, staging, approval-triggered activation, discovery, and TTS
- [x] 6.4 Load-test builds alongside Quick Chat and character speech; verify existing latency/error budgets and `opus-40k` output remain stable
- [x] 6.5 Exercise duplicate submission, callback loss/replay, worker crash, bad transcript, traversal/symlink/non-regular/changing local input, checksum mismatch, failed load, failed activation, rollback, registry drift, and deletion
- [x] 6.6 Run `openspec validate build-custom-kokoro-voices --strict`
