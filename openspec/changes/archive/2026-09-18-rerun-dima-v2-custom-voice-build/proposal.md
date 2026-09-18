## Why

The strict Dima v2 custom-voice build exhausted its six-hour worker deadline after writing a legacy best-voice checkpoint but before producing a result or immutable artifact. A clean, evidence-preserving rerun is needed with enough runtime to finish the same authorized 6,000-step search and qualify Dima v2 without disrupting the active Dima v1 voice.

## What Changes

- Preserve the failed job's checkpoint and safe failure evidence as read-only diagnostic material; do not represent it as a completed or faithfully resumable build.
- Create a new rerun job and output identity using the same authorized adaptation inputs, exclusion of `adapt-001`, four untouched held-out samples, seed 137, three fitness texts, and 6,000-step strict search profile.
- Increase the worker deadline from six hours to ten hours for this rerun while retaining live-speech priority, one-worker concurrency, GPU admission, runtime VRAM reserve, cancellation, and health guardrails.
- Perform named preflight checks for the pinned worker image, local Kokoro model availability, input/build-plan digests, output isolation, assigned GPU, free capacity, TTS health, and absence of a conflicting custom-voice worker before launch.
- Establish a persistent, content-free watch that reports worker state, checkpoint freshness, resource activity, final result or safe failure, and TTS health without relying on conversational session memory.
- On successful construction, run clean compatibility and held-out evaluation using the strict `0.68` speaker-similarity threshold, then create the artifact/SBOM evidence needed for HeartCode review.
- Keep `custom-dima` v1 active and selectable until v2 passes objective evaluation, receives the required internal-use admin approval, stages successfully, and passes activation verification; retire v1 only through successful v2 activation.
- Do not deploy the separate `optimize-custom-voice-build-performance` worker changes into this rerun unless that change is implemented and validated independently before launch.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `custom-kokoro-voice-builds`: Define evidence-preserving recovery and clean rerun behavior after a non-resumable timed-out build.

## Impact

- Operational state on Pea under the private custom-voice workspaces, results, locks, and worker container lifecycle.
- The Dima v2 build plan and job identity, worker launch configuration, safe monitoring evidence, postbuild compatibility/evaluation, artifact packaging, and HeartCode review handoff.
- No public API, stable voice ID, active Dima v1 artifact, source recording, authorization scope, or held-out threshold changes.
- The OpenSpec artifacts are the durable restart handoff after the current Codex session cache is cleared.
