# Content-free diagnostic evidence

This record excludes credentials, transcripts, samples, private paths,
attestations, and unrestricted inspection output.

## Initial Pea inventory — 2026-07-22

- Active baseline: `custom-dima` v1 remains active and healthy
- Provider discovery: `cv_custom_dima` present
- Authenticated stable-ID synthesis: HTTP 200 with nontrivial RIFF audio
- Rejected final candidate: sealed Dima v2 artifact present
- Diagnostic-only candidates: two legacy checkpoints present, one from the
  timed-out attempt and one retained by the completed rerun
- Atomic trajectory checkpoints: none retained
- Maximum bounded candidate set: four anchors (v1, final v2, two legacy
  diagnostic-only checkpoints), subject to per-candidate integrity validation
- Build plans inspected: two
- Separately declared development samples: zero
- Comparative outcome: `inconclusive`; no candidate synthesis or ranking started
- Active services, compose configuration, voice mounts, registry, and HeartCode
  state: unchanged

## Minimum recording request

- Provide at least four newly recorded, separately authorized development clips;
  six are preferred for a less noisy ranking.
- Each clip should contain a distinct sentence and use the same intended voice,
  microphone placement, room, gain, speaking pace, and emotional register.
- Clips must be 5–35 seconds, clean mono speech suitable for deterministic 24 kHz
  normalization, with exact transcript sidecars and no clipping or long silence.
- Development audio and transcript identities must be disjoint from all prior
  adaptation recordings and the four previously evaluated release held-outs.
- These clips will select among existing candidates only. Any selected candidate
  will still require a new untouched final-held-out set before release.
