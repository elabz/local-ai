## Context

The working tree already adds `pea-speech-stt`, `pea-speech-tts`, an authenticated Caddy streaming gateway, blackbox health probing, and a `SpeechServiceDown` alert. Both speech containers are pinned by UUID to `GPU-f417c539-26db-94e9-4c8f-c5a775291988`. `nvidia-smi` identifies that device as zero-based physical index 6, while compose comments and Prometheus labels call it GPU 7 using one-based human display numbering. This is not a placement error, but it is an observability ambiguity.

HeartCode's `improve-voice-conversation-quality` change additionally requires correlation across HeartCode, LiteLLM/direct gateway, PEA containers, accounting rows, and GPU execution evidence. Basic health probing alone does not meet that requirement.

## Goals / Non-Goals

**Goals:**

- Provide stable GPU-backed STT and TTS endpoints for HeartCode.
- Make UUID, zero-based physical index, and one-based display slot explicit everywhere.
- Correlate controlled speech requests across the route without logging secrets or content.
- Expose low-cardinality health, request, latency, error, memory-residency, and utilization signals.
- Provide reproducible deployment, validation, and rollback procedures.

**Non-Goals:**

- Replacing Kokoro based only on subjective preference; provider replacement requires separate evidence and proposal.
- Logging or retaining raw audio, transcripts, synthesized audio, authorization headers, or API keys.
- Moving containers merely to make a mutable CUDA index match a logical label.
- Implementing HeartCode UI or persistence changes in this repository.

## Decisions

### 1. UUID is placement identity; indices are annotated metadata

Compose continues to pin speech workloads to the immutable GPU UUID. Inventory and dashboards expose `gpu_uuid`, `physical_index_zero_based: 6`, and `display_slot_one_based: 7` as separate fields. Labels named only `gpu_id: 7` are replaced or supplemented so operators cannot interpret them as a zero-based physical index.

### 2. Keep LiteLLM as the policy plane; add an internal metering data plane

The metering proxy does **not** replace LiteLLM. LiteLLM remains the public
policy/control plane for virtual-key authentication, database accounting,
model aliases, RPM limits, retries, cooldowns, and provider fallback. The PEA
proxy is a private data-plane hop with only two OpenAI-compatible operations:
`POST /v1/audio/transcriptions` and `POST /v1/audio/speech`.

The routes are:

1. Normal STT/TTS: HeartCode → LiteLLM `:4000` → PEA Caddy edge → private
   metering proxy → Speaches/Kokoro.
2. Low-latency streaming TTS: HeartCode backend → PEA Caddy edge `:8201` →
   private metering proxy → Kokoro.

The direct path is a deliberate latency exception because LiteLLM may buffer
streaming audio. It does not accept browser/user credentials. HeartCode holds a
dedicated service credential; Caddy authenticates it, allowlists the speech
endpoint, strips authorization before the internal hop, applies request-size
and concurrency limits, and forwards only secret-free correlation headers.
The metering service is not host-published and accepts traffic only on the
compose network. Speaches and Kokoro are likewise no longer directly exposed.

The proxy preserves request and streaming-response bodies byte-for-byte while
measuring monotonic duration, status, input audio duration when decodable,
TTS input characters, and response bytes. It enforces bounded request bodies,
timeouts, concurrency, and provider/model allowlists as defense in depth, but
does not recreate virtual keys, user quotas, billing, or routing policy.

Speaches STT and Kokoro TTS retain separate health checks and resource limits.
Prometheus uses low-cardinality operation/model/provider/status/fallback
labels; request, call, and turn IDs belong only in sanitized structured logs.

### 3. Add application counters in addition to blackbox health

Blackbox `probe_success` proves reachability but not traffic or GPU execution. Each speech service or a colocated exporter must expose request totals, failures, duration, and workload units (STT seconds; TTS characters/bytes). Operations views combine those with NVIDIA process UUID, memory residency, and sampled utilization.

The proxy exposes `/metrics` only on the private compose network. It records
the requested model and statically configured actual provider/model after
allowlist resolution. A fallback label is accepted only from trusted LiteLLM
headers or determined locally; arbitrary client values never become labels.

### 4. Verification is a controlled correlated probe

An operator probe generates fresh secret-free request/call/turn IDs, performs STT and TTS through the supported HeartCode route, and records timestamps. It verifies gateway/container receipt, expected accounting, process placement on the target UUID, non-zero model memory, and a utilization or execution-counter change during the sampling window.

### 5. Alerts distinguish availability, routing, inventory, and performance

Alerts cover unavailable models, missing correlation in controlled probes, UUID/index inventory mismatch, unexpected CPU fallback, sustained request errors, and sustained latency. Thresholds must use measured baselines and `for` windows to avoid alerting on single short requests.

## Risks / Trade-offs

- **Short GPU bursts evade 15-second samples** → sample more frequently during controlled probes and retain request counters.
- **Correlation creates high cardinality** → keep IDs out of Prometheus labels and redact authorization/content fields.
- **Latest container/exporter tags drift** → pin production images by version or digest before rollout.
- **Health succeeds while inference is broken** → require model-loaded and end-to-end probe evidence, not HTTP health alone.
- **GPU numbering is misunderstood** → display UUID and both explicit index conventions together.

## Migration Plan

1. Commit the existing speech services, gateway, blackbox configuration, and health alert with pinned images and secret handling.
2. Correct ambiguous GPU labels and add request/process/GPU metrics plus dashboards.
3. Deploy STT/TTS/gateway, validate model loading and direct/LiteLLM routes, then enable HeartCode traffic.
4. Run the controlled correlated probe and capture sanitized evidence.
5. Enable sustained-threshold alerts after baseline observation.
6. Roll back HeartCode routing first, then stop speech services; preserve model cache and secrets for a safe redeploy.

## Open Questions

- Which existing PEA dashboard repository/file should own the speech panels?
- Can the pinned upstream speech images expose native Prometheus metrics and correlation headers, or is a sidecar/exporter required?
- What measured p95 latency and error-rate baselines should become paging thresholds?
