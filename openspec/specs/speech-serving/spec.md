# speech-serving Specification

## Purpose
TBD - created by archiving change serve-speech-stt-tts. Update Purpose after archive.
## Requirements
### Requirement: Measured Placement Gate
Before speech services are exposed for downstream use, the implementation SHALL measure STT (faster-whisper small-class variants) and TTS (Kokoro-82M) on dedicated GPU 7 (zero-based index 6, UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988`), recording transcription latency (15/60/120s clips), TTS real-time factor and first-audio latency, VRAM, and TTS throughput at 4 and 8 concurrent syntheses. Placement and the chosen STT model SHALL be committed from these measurements and recorded in this change. Speech inference SHALL not fall back to CPU and SHALL never be scheduled on GPUs serving chat, embedding, or image-generation models.

#### Scenario: GPU engine unsupported
- **WHEN** a speech engine fails on Pascal compute 6.1
- **THEN** deployment is blocked pending a GPU-compatible engine; it does not fall back to CPU

#### Scenario: Dedicated placement preserved
- **WHEN** speech services are deployed
- **THEN** only the dedicated GPU 7 UUID is exposed to them and GPU 8 remains exclusive to image generation

### Requirement: OpenAI-Compatible Speech Endpoints via LiteLLM
The system SHALL serve `/v1/audio/transcriptions` (STT) and `/v1/audio/speech` (TTS, supporting chunked/streaming responses) and register them in the LiteLLM proxy as `heartcode-stt` and `heartcode-tts`, so requests carry virtual-key accounting and observability identical to chat models. Streaming audio passthrough through LiteLLM SHALL be explicitly verified; if it cannot be made to work, a direct-call arrangement with a dedicated key SHALL be documented in this change together with its accounting treatment.

#### Scenario: Accounted transcription
- **WHEN** a client posts audio to `heartcode-stt` through LiteLLM
- **THEN** a transcript is returned and usage is attributed to the calling virtual key

#### Scenario: Streaming synthesis through the proxy
- **WHEN** a client requests streaming synthesis from `heartcode-tts` through LiteLLM
- **THEN** audio chunks arrive before synthesis of the full text completes

#### Scenario: Config reload discipline
- **WHEN** the LiteLLM config gains the speech model entries
- **THEN** the LiteLLM container is restarted (not merely `up -d`) and the models verifiably resolve

### Requirement: Health and Monitoring Integration
Each speech service SHALL expose a health endpoint and be integrated into the existing Prometheus/Grafana monitoring so degradation is observable without inspecting failed requests. The pinned STT model SHALL be resident at service start (no cold-load on first request).

#### Scenario: Degradation visible
- **WHEN** a speech container becomes unhealthy
- **THEN** monitoring reflects the state without a user-facing request having to fail first

#### Scenario: No cold start
- **WHEN** the first transcription request arrives after service start
- **THEN** it is served without model-load delay

### Requirement: Sole speech deployments are never cooled down and fail fast
For the `heartcode-stt` and `heartcode-tts` model groups, each served by a single deployment, LiteLLM SHALL NOT place the deployment into cooldown on errors, so a failure is returned to the caller and the next request is still attempted. Any retry LiteLLM performs for these groups SHALL be at most one, without a fixed delay, so it completes within the caller's own retry budget (HeartCode: 2 s); otherwise LiteLLM SHALL NOT retry them. The settings SHALL be authored in the configuration sources (`gpu-server/models.yaml`, `litellm/config.base.yaml`), regenerated, and pinned by an integration test against the deployed LiteLLM image. Chat groups' cooldown behaviour is unchanged.

#### Scenario: Repeated errors from the only STT deployment
- **WHEN** the sole `heartcode-stt` deployment returns three 500s in a row
- **THEN** the next transcription request is still forwarded to that deployment
- **AND** it is not refused with a cooldown 429

#### Scenario: Retry does not outlast the caller
- **WHEN** a speech request fails with a transient error
- **THEN** LiteLLM retries at most once and without the router's fixed `retry_after` delay, or not at all

#### Scenario: A LiteLLM upgrade changes cooldown behaviour
- **WHEN** the pinned LiteLLM image is bumped to a version that would cool a single-deployment group
- **THEN** the routing integration test fails before the change reaches elm
