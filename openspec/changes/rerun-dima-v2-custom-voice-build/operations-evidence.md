# Content-free operations evidence

This record intentionally excludes credentials, private paths, transcripts,
samples, attestation bodies, and unrestricted inspection output.

## Failed attempt rehydration — 2026-07-21

- Job: `bench-speaker-001-dima-v2-seed-137`
- Worker state: stopped (no matching container present)
- Safe terminal reason: `worker_timeout`
- Legacy checkpoint: present; non-resumable and preserved in place
- Checkpoint size: 523838 bytes
- Checkpoint modification time: 2026-07-20T21:01:10Z
- Checkpoint SHA-256: `17fff7f35c862d3a6c012c7284d6603bc82a9cb1173be0d45785e6933b323b1d`
- `result.json`: absent
- `artifact.pt`: absent
- Pinned r3 image ID: `sha256:d7c2c29f74558929642fcf6751cf82357439feecf812c45ab6679b5969113e7b`
- Pea TTS: running and model-health healthy
- Dima v1 provider ID: `cv_custom_dima` discovered
- Dima v1 stable ID: `custom-dima` returned HTTP 200 with 120572 RIFF bytes
- HeartCode control-plane evidence: prior dynamic catalog check recorded
  `custom-dima` available; no local development compose dependency is used for
  this production Pea build

## Isolated rerun preparation — 2026-07-21

- Job/idempotency identity: `bench-speaker-001-dima-v2-seed-137-rerun-1`
- Rerun destinations: clear before creation; no prior state deleted
- Workspace/result modes: restrictive (`0700` directories, `0600` files)
- Plan SHA-256: `b7c915822512df594306a18b1abc4ff4eb710fc0a14420e6b195d88e2fad89b7`
- Construction IDs: `adapt-002` through `adapt-006`; `adapt-001` excluded
- Held-out samples: 4 declared; construction overlap 0
- Seed/population/fitness/checkpoint/steps/deadline: 137 / 10 / 3 / 100 / 6000 / 36000 seconds
- Manifest digest: matched
- Normalized input digests: 10/10 matched
- Transcript-sidecar digests: 10/10 matched
- Builder revision: `3a38c6030cc4657df073c67ded37cdf7627c4969`
- Worker image ID: `sha256:d7c2c29f74558929642fcf6751cf82357439feecf812c45ab6679b5969113e7b`
- Kokoro runtime digest: `560e5ba33e78597cf35d266a5591c3ce7558dce318b3019fb6d94e28b466080b`
- Kokoro config SHA-256: `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f`
- Kokoro model SHA-256: `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4`

## Named preflight — 2026-07-21

- Host disk free: 35.5 GiB
- Active custom-voice workers: 0
- Shared build lock: available
- Offline Kokoro config/weights load: pass
- Intended worker-visible GPUs: 1
- Admission free VRAM: 6810 MiB (5000 MiB required)
- Runtime reserve: pass (1024 MiB required)
- Initial preflight diagnosis: client-side wait expired while preprocessing;
  Docker and kernel evidence showed no worker OOM or worker error
- Authorized embedding: pass; 276000 frames, 256 dimensions, 36.996 seconds,
  773.6 MiB peak RSS
- Authenticated synthesis: pass; HTTP 200, RIFF, 56346 decoded frames,
  112770 bytes on the corrected frame-count probe
- Immediate pre-launch TTS model health: healthy
- Temporary diagnostic container: removed

## Production rerun launch — 2026-07-21

- Worker: running under the isolated rerun identity
- Image/runtime: exact pinned r3 image with NVIDIA runtime
- Limits: 2 CPUs, 4 GiB memory, read-only root filesystem
- Failed-attempt checkpoint digest after launch: unchanged
- Persistent content-free watch: active at 60-second intervals
- Initial watch state: worker running, checkpoint/result/artifact absent, TTS healthy
- Safe reconnect command:
  `ssh boss@192.168.0.144 /home/boss/local-ai/gpu-server/custom_voice/status_build_watch.sh bench-speaker-001-dima-v2-seed-137-rerun-1`
