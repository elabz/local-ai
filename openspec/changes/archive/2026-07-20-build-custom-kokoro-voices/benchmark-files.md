# Benchmark File Preparation

Prepare at least two authorized adult speakers. Keep all audio, transcripts,
and consent records outside Git in the private benchmark intake root on Pea.

## Record

For each speaker, record 6 adaptation and 4 held-out clips. Use a quiet room,
one microphone position, and read each prompt exactly. Each clip should be
10–20 seconds of clean single-speaker speech.

- Format: WAV, mono, 24 kHz, signed 16-bit PCM
- No music, effects, denoising, compression, clipping, or background speech
- Retake mistakes; the UTF-8 `.txt` sidecar must exactly match spoken words
- Never use held-out clips to build or tune the voice

Normalize only the container format when necessary:

```bash
ffmpeg -i source.wav -ac 1 -ar 24000 -sample_fmt s16 adapt-001.wav
```

## Place

Create one opaque intake directory per speaker/build beneath the configured
private root. Example:

```text
<intake-root>/bench-speaker-001-v1/
  manifest.json
  adaptation/
    adapt-001.wav
    adapt-001.txt
  heldout/
    heldout-001.wav
    heldout-001.txt
```

Use IDs containing only lowercase ASCII letters, digits, and hyphens. Files
must be regular files owned by the approved intake account, must not be
symlinks, and should be readable only by that account and the build service.
Do not place them in this repository, a web root, or the Kokoro voice directory.

## Authorize and checksum

HeartCode retains the actual consent record. `manifest.json` contains only its
opaque authorization ID and `benchmark-only` or production-authorized scope.
Compute an audio SHA-256 after the final conversion:

```bash
sha256sum adaptation/*.wav heldout/*.wav
```

For every sample, record its opaque sample ID, role (`adaptation` or
`heldout`), relative audio path, relative transcript path, audio SHA-256,
language, sample rate (`24000`), channels (`1`), and encoding (`pcm_s16le`).
Minimal example (repeat `samples` for every clip):

```json
{
  "schema_version": "benchmark-intake.v1",
  "speaker_id": "speaker-001",
  "authorization_id": "hc-consent-opaque-id",
  "authorization_scope": "benchmark-only",
  "language": "en-US",
  "samples": [{
    "sample_id": "adapt-001",
    "role": "adaptation",
    "audio_path": "adaptation/adapt-001.wav",
    "transcript_path": "adaptation/adapt-001.txt",
    "audio_sha256": "<64 lowercase hex characters>",
    "sample_rate_hz": 24000,
    "channels": 1,
    "encoding": "pcm_s16le"
  }]
}
```

Then compute the final manifest digest:

```bash
sha256sum manifest.json
```

Submit only the intake ID, manifest SHA-256, and idempotency key to the private
build API. Never submit an absolute path, URL, transcript, audio content,
credential, or consent document through the API or logs.
