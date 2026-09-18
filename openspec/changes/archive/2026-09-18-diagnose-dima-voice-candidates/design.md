## Context

Dima v2's construction scorer selected a candidate at 0.7027 similarity, while
the strict four-sample held-out evaluation measured 0.6179. The existing v1
artifact measured approximately 0.6417 under its prior evaluation. This gap can
mean the walk overfit adaptation transcripts, the construction objective ranks
candidates poorly, or a better candidate existed earlier and was discarded.

Pea already retains immutable v1/v2 artifacts, one legacy timeout checkpoint,
and v2 checkpoints/evidence. Live speech has priority, protected content cannot
enter ordinary logs, and the existing four held-outs must not become a tuning
set merely because their aggregate outcomes are known.

## Goals / Non-Goals

**Goals:**

- Determine whether an existing integrity-valid candidate generalizes better
  than final v2 using short, isolated evaluation work.
- Separate development candidate selection from final release qualification.
- Preserve comparable provenance, compatibility, WER, speaker-similarity, and
  cross-sample consistency evidence without exposing protected material.
- Make a bounded recommendation before authorizing another multi-hour build.

**Non-Goals:**

- Activating, staging, publishing, or changing the stable `custom-dima` mapping.
- Reclassifying the four existing release held-outs as development inputs.
- Treating an unsafe or incomplete checkpoint as a releasable artifact.
- Relaxing the 0.68 release threshold or beginning a new voice walk.

## Decisions

### 1. Require a distinct development set before comparative ranking

Candidate selection will use newly authorized development recordings that are
disjoint from adaptation inputs and the four previously used release held-outs.
The same development samples, text policy, pinned runtime, ASR, and speaker
encoder will be used for every candidate. If no valid development set exists,
the diagnostic stops after inventory rather than tuning against release data.

This is preferred over reusing the release held-outs because repeated candidate
comparisons would leak release evidence into model selection.

### 2. Inventory candidates before loading tensors

The diagnostic will enumerate only explicit candidate classes: active v1,
sealed final v2, the preserved timeout candidate, and atomic v2 checkpoints.
Each entry records safe provenance, digest, serialization, step/checkpoint
position, and eligibility. Tensor loading uses restricted weights-only or the
validated checkpoint-v2 decoder; foreign, mutable, malformed, non-finite, or
identity-mismatched candidates are rejected before synthesis.

The legacy timeout tensor may be evaluated diagnostically after digest and
tensor validation, but remains ineligible for activation because it lacks a
completed result envelope.

### 3. Use one bounded candidate-comparison harness

Each eligible diagnostic candidate runs in the same pinned Kokoro environment
with read-only candidate and development inputs, no Docker socket, bounded CPU,
memory, PIDs, GPU visibility, and live-speech health/activity guardrails. The
harness records aggregate and per-sample content-free WER and similarity,
minimum similarity, dispersion, compatibility, runtime, and safe failures.

Candidates are evaluated sequentially. The diagnostic pauses or aborts rather
than competing with live inference, and it does not require a production image
or service restart.

### 4. Rank by generalization, not construction fitness

The report will compare candidates primarily by mean development speaker
similarity, then minimum/dispersion and WER within fixed thresholds. It will
include v1 and final v2 as anchors and label construction fitness separately so
it cannot be mistaken for release evidence.

A diagnostic winner is only a recommendation for a fresh release-qualification
cycle using new untouched final held-outs. It is never directly activatable.

### 5. Fail closed and preserve current service state

The output is an immutable, digest-bound, content-free report. Missing
development authorization, fewer than the required samples, candidate identity
failure, runtime incompatibility, or incomplete evaluation produces a safe
inconclusive/reject outcome. No diagnostic outcome updates the Pea registry,
provider mounts, HeartCode catalog, or v1 state.

## Risks / Trade-offs

- [No separate development recordings are available] → Stop after inventory and
  request new recordings; do not consume release held-outs for tuning.
- [Few development clips produce a noisy ranking] → Require a minimum sample
  count and report minimum and dispersion alongside the mean.
- [Legacy checkpoints use different envelopes] → Validate by the matching
  restricted format and label incomplete-result candidates diagnostic-only.
- [Many checkpoints create unnecessary GPU work] → Preselect a bounded,
  provenance-based set across the search trajectory rather than evaluating every
  checkpoint.
- [Development winner fails fresh release held-outs] → Treat this as expected
  uncertainty; activation still requires the unchanged release process.
- [Diagnostic work affects live TTS] → Run sequentially with existing admission,
  health, activity, and VRAM-reserve guardrails; live speech wins.

## Migration Plan

1. Add and test the restricted inventory and comparison report schemas locally.
2. Validate a newly authorized development manifest and prove it is disjoint
   from adaptation and prior release-held-out digests.
3. Deploy only the diagnostic tooling to Pea; do not restart speech services.
4. Inventory and validate the bounded candidate set, then run sequential short
   evaluations under live-service guardrails.
5. Seal the comparison report and record one of: retain v1, fresh-qualify an
   existing candidate, redesign the builder, or inconclusive.
6. Rollback consists of stopping the diagnostic container and retaining its
   restricted evidence; active runtime state is unchanged throughout.

## Open Questions

- How many newly authorized development recordings are immediately available?
- Which atomic v2 checkpoints were retained beyond the final artifact, and what
  bounded trajectory sample can be compared without redundant work?
