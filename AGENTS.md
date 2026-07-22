# Local-AI project memory

## Repository coordination

- This repository owns the Pea inference runtime. The sibling HeartCode control plane is at `/Volumes/T7/Web/heartcode`.
- Coordinate custom-voice contract changes across both repositories, but keep implementation and OpenSpec task status separate.
- Use the repository OpenSpec skills for proposal, implementation, and archive workflows. Do not mark an end-to-end task complete until the live private runtime has been probed.

## Private speech topology

- Pea is reached as `boss@192.168.0.144`; HeartCode development containers run locally.
- The authenticated speech gateway is Pea port `8201`; the internal metering/control boundary is port `8200`.
- `speech-tts` is Kokoro. Stable custom IDs use `custom-<name>`; Kokoro provider files use `cv_custom_<name>` because hyphens are parsed as blend syntax.
- Custom voice artifacts, registries, SBOMs, mappings, and attestations are private operational data. Do not print credentials or full attestations in command output.

## Custom voice release policy

- Custom voices are for private internal use on Pea through HeartCode, not public distribution.
- Activation requires exact artifact and SPDX SBOM digests plus a HeartCode admin attestation for scope `internal_pea`, speaker authority, no redistribution, and acknowledged unresolved license findings.
- An SPDX unresolved-license count is not a vulnerability count. It records packages whose license could not be mapped automatically.

## Verification standard

- Verify all three layers: provider discovery (`cv_custom_*`), stable gateway synthesis (`custom-*`), and HeartCode catalog/preference health.
- A successful activation must produce valid audio and leave HeartCode `published`/healthy and Pea registry `active` for the exact version.
- The HeartCode preference and chat paths must use the dynamic voice catalog. Custom previews must use the authenticated direct Pea route, not the built-in-only LiteLLM voice mapping.

## Kokoro custom-voice findings

- The current builder uses KVoiceWalk-style search over Kokoro voice-style tensors. It does not fine-tune Kokoro weights and is not equivalent to zero-shot speaker cloning with a learned speaker encoder.
- Treat construction fitness as an optimization diagnostic only. Repeated optimization against Resemblyzer can overfit its speaker-verification embedding and regress on unseen recordings even when synthesis remains intelligible.
- Dima v2 demonstrated this failure mode: construction fitness improved, but strict held-out speaker similarity fell below both the `0.68` release gate and the prior v1 result; very low held-out WER showed that intelligibility/transcript alignment was not the primary defect.
- `adapt-001` is a known clipping/outlier sample and must remain excluded. The retained adaptation samples passed intake and were internally consistent; do not characterize them as corrupt without new evidence.
- Do not rerun a longer single-seed search as the default response to weak similarity. Prefer multiple shorter seeded searches, retained candidate checkpoints, per-reference scoring, a worst-reference/dispersion penalty, and an independent development set for candidate selection.
- Candidate selection requires newly recorded development clips disjoint from prior adaptation and release-held-out material. Request at least four; prefer six. Keep a separate untouched final-held-out set for release qualification.
- Record development clips with exact transcripts and consistent room, microphone placement, gain, pace, and emotional register. Require clean 5–35 second mono speech with no clipping or long silence.
- Use more than one speaker representation when redesigning similarity scoring. Resemblyzer is useful verification evidence, not a complete proxy for human-perceived identity; retain human listening as a finalist-selection step.
- A post-Kokoro voice-conversion system may improve cloning while retaining Kokoro for text generation, but it adds another inference model and is not a pure Kokoro voice pack. Treat that as an architecture change, not a builder tweak.

## Production build and review lessons

- Production custom-voice builds run on Pea and must not depend on HeartCode's `docker-compose.dev.yml`. Use an isolated, resource-bounded worker and leave the existing speech runtime and active voice untouched during construction and qualification.
- A completed worker is not an activated voice. Require immutable result/artifact validation, compatibility synthesis, strict untouched-held-out qualification, SBOM and attestation gates before activation.
- Preserve the prior active version when a candidate is rejected or placed in private review. A newer review version does not replace the currently published version; admin views must expose version history clearly enough to distinguish them.
- New or rejected voices may be made available for authenticated admin audio evaluation without public catalog publication. Keep preview/review authorization separate from Quick Chat/public availability.
- Terminal Slack notification is useful for long Pea builds, but it must report only safe terminal state and must not expose credentials, private paths, transcripts, attestations, or artifact contents.
- HeartCode frontend service workers must skip non-HTTP(S) requests such as `chrome-extension:` before calling Cache APIs. In Vite development, stale service-worker or optimized-dependency chunk references can produce hashed-chunk 404s; clear old workers/caches and verify all served dependency assets after frontend changes.
