## Why

HeartCode now depends on GPU-backed STT and TTS services on PEA, but the local-ai repository has speech deployment, gateway, and monitoring changes without an OpenSpec change describing their contract, rollout state, or remaining operational work. The GPU is also described inconsistently: UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988` is physical index 6 (zero-based) while human-facing configuration calls it GPU 7 (one-based logical slot).

## What Changes

- Deploy dedicated Speaches STT and Kokoro TTS services on the speech GPU, plus an authenticated direct-stream gateway for HeartCode.
- Define GPU identity using immutable UUID plus explicit zero-based physical index and one-based display slot.
- Add speech health probes and alerts without exposing credentials, audio, or transcript content.
- Add request/call/turn correlation, request counters, latency/error metrics, GPU residency/utilization evidence, and a controlled end-to-end probe.
- Document rollout, rollback, accounting boundaries, and the evidence HeartCode operators use to verify the complete route.

## Capabilities

### New Capabilities

- `heartcode-speech-runtime`: GPU-backed STT/TTS serving, authenticated streaming, and verifiable speech routing for HeartCode.

### Modified Capabilities

- `gpu-rebalance`: Reserve one physical GPU for speech and describe GPU identity without confusing logical display numbering with discovered physical indices.

## Impact

- `gpu-server/docker-compose.yml`, speech gateway/bootstrap files, Prometheus/blackbox configuration, alert rules, dashboards, and operator documentation.
- PEA GPU UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988` (physical index 6, display slot 7).
- HeartCode and LiteLLM coordination for secret-free correlation headers and accounting verification.
- Brief service restarts during rollout; existing model caches and unrelated GPU workloads remain untouched.
