## Why

Dima v2 completed construction with a 0.7027 construction similarity but fell to
0.6179 on untouched held-outs, below both the strict 0.68 release threshold and
v1's prior approximately 0.6417 result. Before spending another multi-hour Pea
build, we need a bounded diagnostic that determines whether an existing candidate
generalizes better and whether construction ranking is selecting the wrong tensor.

## What Changes

- Inventory the immutable v1 and v2 artifacts, the preserved timeout candidate,
  and any integrity-valid intermediate candidates without modifying them.
- Require a separately authorized development evaluation set; the four existing
  release held-outs remain excluded from candidate selection and parameter tuning.
- Evaluate eligible candidates with the pinned Kokoro runtime, identical text and
  scoring policy, bounded isolated resources, and live-speech priority.
- Produce a content-free comparison report covering aggregate similarity, WER,
  consistency, compatibility, provenance, and candidate eligibility.
- Recommend whether to retain v1, promote an existing candidate into a new release
  qualification cycle, or redesign the builder. The diagnostic never activates a
  voice or changes the stable `custom-dima` mapping.

## Capabilities

### New Capabilities

- `custom-voice-candidate-diagnostics`: Safe inventory, development-set evaluation,
  and comparison of preserved custom Kokoro voice candidates before another build.

### Modified Capabilities

- `custom-kokoro-voice-builds`: Require construction candidates and checkpoints to
  be diagnosable without treating release held-outs as a tuning set or weakening
  the final release gate.

## Impact

- Affects private custom-voice diagnostic/evaluation tooling and tests in
  `gpu-server/custom_voice` and `gpu-server/tests`.
- Adds restricted diagnostic evidence beneath the existing private custom-voice
  storage topology on Pea.
- Does not change public APIs, HeartCode activation contracts, active registry
  state, live Kokoro mounts, or the v1/v2 release thresholds.
