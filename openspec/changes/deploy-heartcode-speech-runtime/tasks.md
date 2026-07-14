## 1. Capture and harden the existing deployment work

- [x] 1.1 Add dedicated Speaches STT and Kokoro TTS services pinned to `GPU-f417c539-26db-94e9-4c8f-c5a775291988`
- [x] 1.2 Add model-aware STT/TTS health checks, persistent speech model cache, resource limits, and service networking
- [x] 1.3 Add an authenticated Caddy direct-stream gateway for TTS
- [x] 1.4 Add blackbox speech health scraping, Prometheus rule loading, and the initial `SpeechServiceDown` alert
- [x] 1.5 Pin every new production image by version or digest, including blackbox exporter, and document secret provisioning

## 2. Correct GPU inventory semantics

- [x] 2.1 Replace ambiguous `gpu_id: '7'` monitoring metadata with explicit GPU UUID, zero-based physical index 6, and one-based display slot 7
- [x] 2.2 Add an inventory check that discovers the UUID-to-index mapping and warns when recorded metadata differs
- [x] 2.3 Update PEA setup/operator documentation and dashboard labels with the explicit numbering convention

## 3. Add route and runtime observability

- [x] 3.1 Forward allowlisted speech request/call/turn correlation headers through the direct gateway and emit them in sanitized structured access logs
- [x] 3.2 Export STT/TTS request totals, failures, latency, workload units, requested/actual model, provider path, and fallback without high-cardinality metric labels
- [x] 3.3 Export speech process GPU UUID, discovered physical index, model memory residency, and sampled execution/utilization metrics
- [x] 3.4 Add operations dashboard panels for health, traffic, latency, errors, process placement, memory, and utilization

## 4. Controlled verification and alerting

- [x] 4.1 Add a controlled end-to-end probe correlating HeartCode, LiteLLM/direct gateway, PEA containers, accounting rows, and GPU evidence
- [x] 4.2 Add alerts for missing controlled-probe correlation, UUID/index mismatch, unexpected CPU fallback, and unavailable speech models
- [x] 4.3 Establish measured p95 latency/error baselines and add sustained-threshold alerts with non-flapping `for` windows
- [x] 4.4 Validate direct and LiteLLM routes, model loading, request accounting, and GPU execution; retain sanitized evidence

## 5. Rollout and documentation

- [x] 5.1 Document deployment order, health gates, HeartCode enablement, rollback, data retention, and secret rotation
- [x] 5.2 Run `openspec validate deploy-heartcode-speech-runtime --strict` from a workstation with the OpenSpec CLI
