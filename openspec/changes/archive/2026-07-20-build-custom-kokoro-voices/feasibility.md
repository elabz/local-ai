# Custom Kokoro Voice Feasibility Record

## Pinned runtime inventory

Inventory date: 2026-07-15. Evidence was collected from the running PEA
container and the compose definition in this repository.

### Runtime identity

- Compose and the deployed container both resolve to
  `ghcr.io/remsky/kokoro-fastapi-gpu:v0.6.0@sha256:560e5ba33e78597cf35d266a5591c3ce7558dce318b3019fb6d94e28b466080b`.
- The image reports Kokoro-FastAPI `v0.6.0`, uses Kokoro v1, and runs with
  `use_gpu=True` on the dedicated speech GPU.
- Voice packs live at the fixed container path `/app/api/src/voices/v1_0`.
  The current compose service has no voice-pack volume, so files added to a
  running container are lost on container replacement.

### Discovery, naming, and loading

- Discovery scans the immediate entries of the voice directory on every
  `list_voices()` call, accepts every filename ending in the case-sensitive
  suffix `.pt`, strips that suffix, sorts the names, and does not recurse.
- A synthesis request is accepted only when its resolved voice name exactly
  matches a discovered filename. OpenAI aliases and weighted `+`/`-` voice
  combinations are handled before this membership check.
- There is no explicit voice-ID grammar in the provider. The first character
  of the voice name selects the language pipeline unless `lang_code` or the
  server-wide override is supplied. A custom registry must therefore impose
  its own reserved grammar and always supply/record language rather than rely
  on a custom ID's first character.
- `get_voice_path(name)` constructs `<voice-dir>/<name>.pt`; public synthesis
  first requires membership in the non-recursive directory listing, which
  prevents an undiscovered path from being selected. The future control plane
  must still reject separators, dot segments, built-in collisions, aliases,
  and combination syntax before touching storage.
- Loading reads the whole file and calls `torch.load(..., map_location=device,
  weights_only=True)`. This is materially safer than unrestricted pickle
  loading, but packs must remain internally produced and digest-verified; the
  compatibility runner remains a required isolation boundary.

### Artifact contract

- The serialized object is a single `torch.Tensor`, not a state-dict or a
  training checkpoint. A sampled bundled pack is finite `torch.float32` with
  shape `[510, 1, 256]`; bundled packs are serialized with `torch.save` and
  use `.pt` filenames. The first dimension is utterance/token-style dependent
  and must not be hard-coded without checking every selected builder output.
- The exact acceptance contract for a candidate artifact is: safe
  `weights_only=True` load on CPU and the target device; a tensor of the
  builder-declared compatible shape and `float32` dtype; all values finite;
  successful use by the pinned `KPipeline.generate_from_tokens`; and non-empty,
  finite, decodable 24 kHz mono output for every fixed compatibility phrase.
- The immutable artifact manifest must additionally bind the SHA-256 digest,
  byte size, stable voice ID, version, language code, builder/model/config
  revisions, Kokoro-FastAPI image digest, source-manifest digest, and evaluation
  report. These are registry requirements, not fields embedded in the `.pt`.

### Refresh and concurrency implications

- Directory discovery is dynamic, so a newly created filename can appear in
  voice listings without a process restart.
- Loaded tensors are cached indefinitely by `<absolute path>:<device>` in the
  singleton Kokoro backend. Replacing bytes at an existing path does not
  invalidate the cache and can make discovery/storage disagree with synthesis.
- The pinned provider exposes no production cache invalidation or atomic
  voice-pack reload operation. Its optional development unload endpoint unloads
  the model rather than providing a version-aware pack swap.
- Consequently, an active filename must never be overwritten. Each version
  needs a unique provider filename and immutable path. Stable-ID switching
  cannot be implemented safely inside this unmodified provider. Unless the
  later concurrent refresh experiment proves a controlled extension safe, use
  a drained blue/green provider replacement with a versioned read-only voice
  mount and switch traffic only after health probes pass.

### Inventory conclusion

The pinned runtime can consume internally generated Kokoro voice tensors, and
its `weights_only=True` loader is suitable for a restricted compatibility
runner. It does not itself provide persistence, artifact identity, validation,
safe replacement, stable-ID indirection, or atomic rollback. Those functions
must remain in the proposed registry/control plane, with blue/green replacement
as the current default activation design.

### Blue/green concurrency implementation evidence (2026-07-17)

The host-side coordinator now builds an immutable read-only voice snapshot for
the inactive slot, starts that provider, requires stable-ID discovery and a
non-empty synthesis probe, drains the active slot, atomically switches traffic,
and only then commits the exact registry version/digest. Discovery, synthesis,
drain, or registry failures restore the prior traffic slot and leave the prior
registry mapping intact. Provider lifecycle operations remain injected so the
private control plane and workers do not receive a Docker socket.

A deterministic concurrent-routing test holds one synthesis lease on `blue`,
switches traffic, verifies a new request selects `green`, verifies `blue` does
not report drained while the original request is active, and then verifies it
drains after that request completes. The persisted route survives controller
restart. This proves the local drain/switch algorithm; task 5.3 remains open
until the pinned production provider is exercised under concurrent synthesis
and the latency/error evidence is recorded on Pea.

### Live-speech interference sample (2026-07-17)

While `bench-speaker-001-production-10000` was actively walking on the shared
speech GPU, a bounded content-free probe issued ten fixed synthetic TTS calls
across Quick Chat and character-style workloads at concurrency two. All ten
requests succeeded and all ten returned an Ogg container under the required
`opus-40k` request profile. There were no synthesis errors. Observed p95 was
`2.1969` seconds, which exceeds the pre-recorded warm single-request baseline
of `0.49` seconds and its 25-percent limit of `0.6125` seconds.

This is an interim reject, not yet an attribution to the build: the prior
baseline used controlled warm requests rather than the identical concurrency-
two workload. Rerun the exact ten-request probe after the worker exits. Release
fails closed if the matched no-build baseline shows that the active build caused
the excess, or if either matched run breaches the established live-speech
latency budget. Task 6.4 remains open pending that matched comparison.

### Production-walk isolation finding (2026-07-17)

The in-progress `bench-speaker-001-production-10000` container was launched
outside the pinned launcher. Inspection found no Docker memory or PID limit, a
writable container root, a read-write mount of the entire private tree, and an
older worker image without the current deadline, cancellation, live-health, or
inference-idle checks. Preserve its output as restricted quality research, but
do not treat it as passing capacity, privacy-isolation, live-priority, or
production provenance gates and do not activate it.

The checked-in launcher now verifies the locally resolved worker image digest
before launch, rejects missing/symlinked private roots, mounts intake separately
read-only, exposes only workspace/results/cache/lock roots read-write, and
retains CPU, RAM/swap, PID, read-only-root, capability, privilege, GPU, network,
and timeout controls. A qualifying benchmark must be rerun through this exact
launcher and record the resulting container/image evidence.

The qualifying worker result now also records checkpoint-sampled peak observed
GPU use, minimum free GPU memory, peak worker RSS, and peak private job bytes.
It explicitly writes checkpoints, artifacts, previews, and result metadata as
`0600`. The older research container's observed checkpoint is `0644`, further
confirming that its output must be treated as unsealed research material rather
than a production artifact.

### Qualifying rerun preflight (2026-07-17)

Pea now has `local-ai-custom-voice-worker:qualifying-v2`, image ID
`sha256:012a1516491f0b805719568682c1d872e553a18e1db20f6c4e3508b1aa9644f6`.
The embedded worker SHA-256 is
`1ea6ccdb077612ce42b879bf20762e9c5c747d973bb0009ec78b24d7225a13c7`;
its source compiles without writing to the image layer. The dedicated lock root
exists with mode `0700`.

The authorized intake was revalidated in a no-network, read-only-root container
with intake mounted read-only and only the workspace root writable. The new
opaque workspace is `bench-speaker-001-qualifying-v1`; it binds the expected
manifest digest, contains six adaptation and four held-out samples, uses seed
42 and 10,000 steps, sets a 21,600-second deadline, requires 5,000 MiB admission
free VRAM and 1,024 MiB runtime reserve, and explicitly requires both live
health and inference-activity controls. Its plan is `0600`, and no workspace
file has group or other permission bits. Do not launch it until the older
research walk releases the concurrency lock and speech GPU.

Immutable sealing now also requires the exact build-result schema, pinned
builder identity, digest-shaped build/manifest/image references, positive step
and duration evidence, and non-negative checkpoint-sampled resource metrics.
Older outputs without that evidence fail with a safe resource-evidence reason
before any version directory is published.

The corrected launcher was exercised in no-launch mode on Pea and returned
`ready` for the exact qualifying workspace and `qualifying-v2` image digest.
The candidate container can read its plan as the service UID and reach the
pinned TTS `/health` endpoint plus the speech meter's content-free
`/internal/activity` endpoint on the production network. The meter was rebuilt
with active-request and idle-time tracking, including cleanup for requests
rejected before upstream proxying, so malformed input cannot leave a stale
activity count. A post-rebuild authenticated boundary probe returned HTTP 200
and an Ogg `opus-40k` response. The GPU worker remains unlaunched while the old
research walk is active.

## Candidate technique inventory

Candidate review date: 2026-07-15. Repository revisions are pinned below so a
later benchmark does not silently test different code.

| Candidate | Pinned revision | Technique | Produces the pinned `.pt` contract? | License finding | Benchmark disposition |
|---|---|---|---|---|---|
| RobViren/KVoiceWalk | `3a38c6030cc4657df073c67ded37cdf7627c4969` | Searches the space of existing Kokoro style tensors. It selects/interpolates bundled voices, applies stochastic tensor mutations, synthesizes the supplied transcript and a second phrase, then scores target-speaker similarity (Resemblyzer), cross-phrase self-similarity, and acoustic features. This is derivative style-tensor optimization/adaptation; it is neither speaker-embedding extraction nor acoustic-model fine-tuning. | Yes. It serializes the best single tensor with `torch.save`, intended for Kokoro `.pt` loading. | Repository code is Apache-2.0. Kokoro code/weights are Apache-2.0. Dependency/model notices and redistribution of bundled voice packs still require a release-time SBOM and legal review. | **Primary benchmark candidate.** Only reviewed project that directly emits the required pack format. Non-determinism, weak objective metrics, dependency versions, and Pascal/CUDA compatibility must be tested. |
| BovineOverlord KVoiceWalk GPU/GUI fork | `9539108a5a08fb6e6a786c698ef7841f078a6997` | Same style-tensor random-walk/adaptation lineage with GPU/GUI queue changes; not training or direct embedding extraction. | Yes, by the same `torch.save(tensor)` path. | Repository code is Apache-2.0, subject to the same dependency/model and bundled-pack review. | **Secondary candidate only.** Benchmark only if its fork delta demonstrates material throughput, recovery, or operational advantages over the primary revision. |
| Ashish-Patnaik/KokoClone | `dd6bd3acd3010dc223978839761db74957195f98` | Zero-shot audio-to-audio voice conversion. Kokoro first synthesizes with a bundled voice; a Kanade reference-conditioned converter then re-voices the waveform. It performs inference-time reference conditioning, not Kokoro embedding extraction, adaptation, or fine-tuning. | No. Output is converted waveform audio; no reusable Kokoro `.pt` pack is produced. | Repository declares Apache-2.0. Kanade model/code and every downloaded model revision require separate verification before use. | **Rejected for this change.** It changes the online inference architecture and cannot satisfy exact-pack activation. It would need a separate provider proposal. |
| Upstream StyleTTS2 training/fine-tuning | `yl4579/StyleTTS2` lineage | Full model training or fine-tuning/adaptation using transcribed corpora and auxiliary ASR/SLM components. | No demonstrated compatibility. Kokoro removed/changed StyleTTS2 components and upstream Kokoro does not publish its training/export pipeline; a StyleTTS2 checkpoint is not a Kokoro style tensor. | StyleTTS2 code is MIT, but pretrained checkpoints and training datasets have their own terms. | **Rejected at inventory gate.** Treating architectural ancestry as artifact compatibility would be unsafe; requires a separate research effort and generally far more data/compute. |
| Built-in Kokoro voice blending | Pinned Kokoro-FastAPI v0.6.0 | Arithmetic mean/weighted combination of existing voice tensors; uses no sample audio and learns no speaker representation. | Yes, but only as a blend of bundled packs. | Covered by pinned Kokoro code/weight terms. | **Not a custom-voice candidate.** Must never be represented as training or cloning. |

### Candidate conclusion

KVoiceWalk is the only identified, source-available candidate that both consumes
speaker sample audio/transcript material and emits the exact Kokoro voice-tensor
class expected by the pinned provider. It is therefore admitted to feasibility
benchmarking, not selected for production. KokoClone is useful evidence that a
different architecture can provide zero-shot conversion, but it fails this
change's immutable Kokoro-pack requirement. StyleTTS2 training is not a drop-in
Kokoro pack builder, and ordinary voice blending does not use the target
speaker. If KVoiceWalk fails the recorded quality, repeatability, license,
capacity, or live-interference thresholds, the required result is a no-go.

## Production intake preflight (2026-07-17)

Intake `bench-speaker-001-v1` contains six adaptation pairs and four held-out
pairs. The held-outs were not supplied to or inspected by a builder. All audio
files are regular, non-symlink files with mode `0600`; the manifest paths are
relative and its ten audio SHA-256 values were computed and verified against
the exact source WAV bytes. The opaque production authorization reference is
populated consistently in the manifest and consent-reference file. The current
manifest digest is
`c95b635b8a3490ccc9dbd366c4cb814e7f46e0e33686025c9cb437211568f82f`.

Measured audio is mono 32 kHz signed 16-bit PCM. Adaptation duration is about
103.2 seconds and held-out duration is about 83.3 seconds. `adapt-001` and
`adapt-006` reach 0 dBFS; `adapt-005` peaks at approximately -0.09 dBFS. Under
the versioned PCM16 policy, the first two contain only isolated ceiling contact
and are review findings rather than rejection or proof of clipping. They are
accepted for the restricted benchmark subject to later human preview. Originals
must remain immutable; any required 24 kHz conversion is a
deterministic workspace derivative with its own digest, never an overwrite of
intake audio.

### Builder admission finding

Upstream KVoiceWalk accepts one target WAV and transcript per random-walk run.
The implemented restricted `kvoicewalk-multireference.v1` wrapper instead forms
a normalized embedding centroid from all six adaptation recordings, cycles the
adaptation transcripts during seeded scoring, excludes held-outs from
construction, checkpoints improvements, and records build provenance. It
remains stochastic style-tensor adaptation rather than acoustic-model training.

The production host has only about 5.5 GiB free on the dedicated live speech
GPU while its healthy STT and TTS services are running. The candidate reports
about 4 GiB use. The pinned isolated worker now admits only one job when at
least 5,000 MiB is free; the short production-GPU benchmark must measure actual
peak use and live-speech impact before a full walk. Clean compatibility,
supply-chain, clipping, and atomic registry-switch foundations are implemented.

**Gate result: implementation and benchmark admitted; release undecided.** The
intake passed root-confined digest verification and the selected preprocessing
profile, including deterministic 24 kHz workspace generation. A second speaker
is required only before general-purpose rollout. Benchmark task 1.3 remains
incomplete until the worker runs on Pea and records quality, compatibility,
resource, repeatability, and live-interference results. Activation remains
separately gated on those results, human approval, and exact supply-chain
evidence.

## Versioned restricted-pilot thresholds

Threshold policy: `restricted-production-speaker.v1`, recorded before the
10,000-step result is evaluated.

| Gate | Pass threshold |
|---|---|
| Artifact compatibility | Exact digest loads with `weights_only=True` in the pinned Kokoro v0.6.0 image; tensor and both fixed-phrase outputs pass dtype, shape, finiteness, range, channel, rate, and non-empty checks. |
| Held-out intelligibility | Mean normalized word error rate across all four held-outs is at most `0.20` using pinned `faster-whisper-small.en`. |
| Held-out speaker similarity | Mean Resemblyzer cosine similarity between each held-out reference and its artifact-generated transcript is at least `0.65`. |
| Human naturalness | The authorized reviewer explicitly accepts every protected held-out preview for intelligibility, identity, artifacts, and the isolated peak-contact samples. Pending, missing, or mixed review fails release closed. |
| Build capacity | One worker only; completes within six hours; container RAM at most 4 GiB; private job data at most 5 GiB; continuous visible-GPU free reserve never below 1,024 MiB. |
| Live interference | Speech TTS remains healthy; no build-correlated synthesis errors; measured p95 latency does not rise more than 25 percent above the same-request pre-build baseline; output remains accepted `opus-40k`. |
| Repeatability | A second walk using the same immutable inputs/profile records its own seed and revisions, passes compatibility, and does not fall below either objective held-out threshold. Bit-identical voice tensors are not required for a stochastic walk. |
| Supply chain | Exact internally activated artifact has an SPDX JSON SBOM and an authenticated HeartCode admin attestation acknowledging its exact license findings, speaker authority, Pea-only use, no redistribution, and the artifact/SBOM digests. |

The selected benchmark builder is KVoiceWalk revision
`3a38c6030cc4657df073c67ded37cdf7627c4969` through the local
`kvoicewalk-multireference.v1` wrapper. It is Apache-2.0 code performing
style-tensor adaptation, not acoustic-model training. Kokoro code/weights are
Apache-2.0; every packaged dependency, model, and redistributed base voice
still requires exact SBOM inventory and authenticated HeartCode admin review.
Inventory findings are therefore sufficient to benchmark, not sufficient to
activate.

Capacity placement is Pea GPU UUID
`GPU-f417c539-26db-94e9-4c8f-c5a775291988`, shared with speech under
concurrency-one admission, a 5,000 MiB start threshold, a continuous 1,024 MiB
reserve, checkpointing, and live-health observation. A second GPU host is not a
prerequisite for this restricted speaker build.

If the builder fails any compatibility, objective quality, human review,
capacity, live-interference, repeatability, licensing, or approval gate, the
recorded outcome is **no release** for this artifact. The implementation and
evidence may be retained privately, but the voice is not staged as production
approved, activated, advertised as successful cloning, or substituted with an
unmeasured blend. A different architecture requires a separate proposal.

## Live-interference observation (2026-07-17)

During the 10,000-step production-speaker walk, a single controlled internal
TTS request completed HTTP 200 in 0.81 seconds. Its output was mono Opus,
48 kHz, 6.49 seconds, and 38,359 bit/s, confirming the accepted `opus-40k`
delivery profile remained intact. The speech meter showed 154 successful TTS
requests with all observed requests in the under-2.5-second histogram bucket;
STT and TTS health remained green.

A bounded four-request concurrency probe then completed all four HTTP 200
responses in 4.95 seconds, with individual totals 2.14–4.89 seconds. The
pre-build four-request baseline was 2.47 seconds wall and 1.83–2.41 seconds
individual. The approximately 100 percent wall-time increase exceeds the
`restricted-production-speaker.v1` 25 percent interference threshold even
though no request failed and GPU free memory stayed above the runtime floor.

This is a **failed live-interference observation**, not permission to activate
the resulting voice. The implementation now exposes a content-free active
speech/idle endpoint and requires subsequent workers to wait for five seconds
of speech idleness before every base-voice synthesis and walk score. Task 6.4
remains open until the hardened worker is retested and meets the budget. The
currently running walk is allowed to finish as benchmark evidence but does not
retroactively pass the release gate.

## Matched qualifying-build live-load result (2026-07-17)

The obsolete unguarded research worker was stopped after preserving its
checkpoint because it could not satisfy a remaining release task. The exact
ten-request, concurrency-two workload was then run without a build: all ten
Quick Chat/character-style requests succeeded with valid `opus-40k` Ogg output,
zero errors, and p95 `1.3502` seconds. The earlier unguarded-build p95 of
`2.1969` seconds was a 62.7-percent regression and therefore failed.

The qualifying worker was launched through the corrected launcher with exact
image ID, service UID, read-only root and intake, 4 GiB RAM/swap, 256 PID and
two-CPU limits, no added capabilities or privilege escalation, concurrency
lock, live health, and inference-idle gating. During that build, the identical
workload again returned 10/10 valid responses with zero errors and p95 `1.5853`
seconds. This is a 17.4-percent increase over the matched no-build result and is
within the recorded 25-percent limit. Task 6.4 passes for the qualifying
profile; the worker continues toward its final artifact.

## Qualifying artifact validation result (2026-07-18)

The qualifying walk completed in `12,463.70` seconds (3 hours 27 minutes 44
seconds) with seed `42` and produced sealed artifact SHA-256
`47508317563dd493b7faece8566bb6ff2629258ee72467ed4f29da8dc5608656`.
The clean, network-isolated compatibility runner used pinned Kokoro v0.6.0,
loaded that exact digest with local pinned model files, and synthesized both
fixed phrases successfully at 24 kHz (99,600 and 93,600 frames). Task 4.5b
therefore passes.

Held-out evaluation processed all four reserved samples. Mean normalized WER
was `0.01905`, passing the `0.20` intelligibility ceiling. Mean Resemblyzer
cosine similarity was `0.64173`, below the pre-recorded `0.65` threshold, so
the objective and release outcomes are **reject**. Human naturalness remains
pending, but cannot override this failed objective gate. The artifact remains
private and must not be staged or activated. Task 1.3 remains open for its
remaining benchmark evidence; this artifact already has a binding no-release
result under `restricted-production-speaker.v1`.

The authorized operator subsequently requested release under the display name
`Dima` and explicitly accepted a digest-specific restricted-speaker exception
lowering the similarity floor to `0.64`. The observed `0.64173` passes that
exception; this does not rewrite the original benchmark, apply to other
artifacts, or establish a general-purpose threshold. Resource evidence records
2,810.23 MiB peak worker RSS, 5,046 MiB peak observed GPU use, 3,146 MiB
minimum observed GPU free, 11,035,480 peak private-job bytes, six adaptation
and four held-out samples, and a 12,463.70-second build. Together with the
matched live-load result, task 1.3 is complete. Production publication remains
independently fail-closed until the exact SBOM and HeartCode internal-use admin
attestation pass.

## Production blue/green concurrency result (2026-07-18)

The pinned production Kokoro image was started as an isolated green candidate
from a digest-verified read-only provider snapshot while the active blue
provider continued serving. The proof exposed and corrected two integration
defects: reserved hyphenated stable IDs were parsed by Kokoro as blend syntax,
and immutable snapshot rotation did not unlock the coordinator-owned prior
directory before removal. Stable `custom-dima` now maps internally to
non-blend provider ID `cv_custom_dima`; the speech proxy applies this mapping
and explicit language while retaining the public stable ID.

After the corrections, overlapping synthesis returned HTTP 200 and valid RIFF
audio from both slots: active blue produced 322,158 bytes in 0.9715 seconds and
green Dima produced 252,044 bytes in 1.0984 seconds. Public traffic was not
switched, and the temporary green validation container was removed afterward.
This production-host evidence completes task 5.3 and confirms drained
blue/green replacement is the safe refresh strategy for the pinned provider.
