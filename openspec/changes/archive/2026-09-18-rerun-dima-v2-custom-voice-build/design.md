## Context

The prior Dima v2 job, `bench-speaker-001-dima-v2-seed-137`, ran with worker image `local-ai-custom-voice-worker:dima-v2-r3`, seed 137, five accepted adaptation samples (`adapt-002` through `adapt-006`), three fitness texts, 6,000 steps, and a 21,600-second deadline. It exited with safe outcome `worker_timeout`. Its last checkpoint was written at `2026-07-20T21:01:10Z`, but no `result.json` or `artifact.pt` was produced. That checkpoint contains only the best voice tensor and lacks the completed step, score, improvement count, and random states required for a deterministic resume.

The prior Dima v1 voice remains active in HeartCode. Its held-out mean speaker similarity was approximately 0.6417 and it was released under a relaxed 0.64 gate; v2 was requested specifically to improve similarity and uses a strict 0.68 held-out gate. The five retained adaptation recordings have strong internal consistency; `adapt-001` remains excluded as the clipping/outlier sample. The four held-out recordings must remain unseen during construction.

This change is an operational rerun using the currently validated r3 worker unless the separate `optimize-custom-voice-build-performance` change has been fully implemented and validated before launch. These artifacts serve as the durable handoff when conversational session cache is cleared.

## Goals / Non-Goals

**Goals:**

- Preserve the failed attempt and its diagnostic evidence without misclassifying it as completed.
- Launch a clean, reproducible rerun with sufficient time to complete the strict search on current Pea hardware.
- Keep live TTS healthy and prioritized throughout the offline build.
- Maintain a durable content-free watch independent of the current Codex session.
- Qualify, package, review, and activate v2 only if every strict gate passes.
- Keep Dima v1 available until v2 activation is demonstrably successful.

**Non-Goals:**

- Resuming the legacy checkpoint as though it contained complete search state.
- Relaxing the 0.68 held-out threshold, reducing three-text fitness, reducing the 6,000-step target, or reintroducing `adapt-001`.
- Activating a partial checkpoint or automatically approving the new artifact.
- Deploying unvalidated performance-optimization code as part of the rerun.
- Publishing or redistributing Dima artifacts outside the private Pea/HeartCode system.

## Decisions

### 1. Preserve the failed attempt and create a new identity

The prior results directory and r3 launch log remain read-only evidence. The rerun uses job ID `bench-speaker-001-dima-v2-seed-137-rerun-1`, a distinct workspace, results directory, launch log, lock identity, and idempotency identity. Before launch, the operator records safe digests and status of the prior checkpoint and verifies that the new destinations do not exist.

Reusing the old output directory is rejected because the worker refuses occupied/completed state inconsistently and the checkpoint cannot reproduce the interrupted walk. Deleting the failed attempt is rejected because it would erase useful evidence.

### 2. Repeat the authorized strict plan with a ten-hour deadline

The rerun retains seed 137, the same manifest and accepted inputs, `adapt-001` exclusion, five adaptation references, four untouched held-outs, population limit 10, fitness-text count 3, checkpoint interval 100, and step limit 6,000. `max_duration_seconds` becomes 36,000.

Ten hours provides margin over the observed six-hour timeout while preserving the same search work. Changing the seed or lowering work would make comparison ambiguous. The worker still yields to production activity, enforces a single build, checks live health, and retains its GPU admission and runtime free-VRAM reserve.

### 3. Use a named preflight before launch

Preflight validates:

- Pea connectivity and adequate host disk space;
- healthy `pea-speech-tts` and successful model-aware health;
- no conflicting custom-voice build container or lock;
- the pinned r3 image identity and local Kokoro config/model availability;
- exact manifest/build-plan digests and the expected adaptation/held-out role counts;
- exclusion of `adapt-001` and absence of held-out references from construction inputs;
- NVIDIA runtime attachment to the intended healthy GPU, required free VRAM, and a short named synthesis probe;
- new output/workspace isolation and restrictive ownership/modes.

Preflight prints only safe state, opaque IDs, digests, counts, resource values, and health. It does not print transcripts, sample paths, audio, environment values, or credentials.

### 4. Make monitoring durable and content-free

The launch runs independently of the client session and writes a restricted launch log. A persistent watch reports at a bounded interval:

- UTC timestamp and worker state;
- CPU and bounded memory/resource observations;
- checkpoint presence, size, and modification time;
- result/artifact presence;
- TTS running/health state;
- safe terminal outcome and reason.

The watch has a stable documented command and log location on Pea, so a new Codex session can recover status from this OpenSpec change. It never emits environment variables, transcripts, sample paths, audio, or unrestricted container inspection.

### 5. Separate construction completion from release

When `result.json` and `artifact.pt` appear, the operator first validates their schema, exact plan/manifest/image identities, seed, 6,000 executed steps, duration, finite tensor, safe digest, and compatibility. Postbuild then evaluates only the four held-out samples with minimum mean speaker similarity 0.68 and the existing WER threshold.

A failure remains a rejected candidate and does not affect v1. A pass produces immutable artifact and SPDX evidence for HeartCode admin review. Human approval remains required for internal Pea-only use. Successful activation must verify provider discovery, registry digest/version, stable-ID gateway synthesis, nontrivial audio format, and HeartCode consumer availability before v1 is retired through the normal activation transition.

## Risks / Trade-offs

- [Ten hours is still insufficient under heavy live-speech pauses] → Monitor checkpoint freshness and active resource use; if it times out again, preserve evidence and implement resumable/early-rejection optimization before another full rerun.
- [The legacy checkpoint contains a promising candidate] → Preserve it for comparison or separately labeled diagnostic evaluation, but do not substitute it for a completed v2 artifact.
- [GPU/NVML instability recurs] → Require a healthy named GPU probe before launch, monitor TTS continuously, and stop the offline worker before considering any host-level recovery.
- [The rerun competes with live inference] → Retain live-activity yielding, one-worker concurrency, admission checks, and runtime VRAM reserve; live TTS wins over build throughput.
- [A cleared session loses operational context] → Store all identifiers, thresholds, decisions, and ordered commands/tasks in this change and keep the watch on Pea rather than in a client-only process.
- [A successful build is activated prematurely] → Treat construction, compatibility, held-out evaluation, packaging, approval, staging, activation, and consumer verification as separate fail-closed tasks.
- [The new performance change becomes partially available] → Use r3 unless `optimize-custom-voice-build-performance` passes its own strict validation, tests, image pinning, and preflight in full.

## Migration Plan

1. After clearing session cache, open this change and use the Pea speech-runtime workflow to rehydrate state.
2. Verify the failed job remains stopped with `worker_timeout`, checkpoint evidence present, and no final artifact/result.
3. Generate the new digest-bound rerun plan and workspace without modifying the prior attempt.
4. Complete named preflight and launch the new worker with a 36,000-second deadline.
5. Start and record the persistent safe watch; periodically verify checkpoint freshness and TTS health.
6. On completion, validate result integrity and run clean compatibility plus strict held-out evaluation.
7. If accepted, package immutable artifact/SBOM evidence and hand off to HeartCode admin approval and activation.
8. Verify every runtime/consumer layer before allowing the normal v2 activation to retire v1.
9. On failure, leave v1 active, preserve rerun evidence, and record the safe reason. Rollback consists of stopping/removing only the rerun worker and leaving all active registry/runtime state unchanged.

## Open Questions

- None required to launch. If preflight shows the r3 image is unavailable or its digest differs from the recorded build environment, stop and reconcile the image rather than substituting an unpinned worker.
