# Speech Serving — Delta for serve-speech-stt-tts

## ADDED Requirements

### Requirement: Measured Placement Gate
Before speech services are exposed for downstream use, the implementation SHALL measure STT (faster-whisper small-class variants) and TTS (Kokoro-82M) on the candidate placements — GPU-8 slice colocated with image generation, and CPU — recording transcription latency (15/60/120s clips), TTS real-time factor and first-audio latency, VRAM, image-generation latency delta under colocated load, and TTS throughput at 4 and 8 concurrent syntheses. Placement and the chosen STT model SHALL be committed from these measurements and recorded in this change. Speech SHALL never be scheduled on GPUs serving chat models or on the faulty card (GPU-f1fa6009).

#### Scenario: GPU slower or unsupported
- **WHEN** a speech engine fails on compute 6.1 or is not meaningfully faster than CPU
- **THEN** it is deployed CPU-only

#### Scenario: Image latency protected
- **WHEN** colocated speech load degrades image-generation latency beyond recorded tolerance
- **THEN** speech is placed on CPU and GPU 8 is left to image generation

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

### Requirement: TTS Fallback Tier
TTS serving SHALL provide Kokoro-82M as the primary engine and Piper (CPU, isolated network service) as an independently addressable fallback, such that the downstream consumer can retry a failed synthesis on the fallback engine.

#### Scenario: Fallback reachable during primary outage
- **WHEN** the Kokoro service is down
- **THEN** the Piper service still accepts and completes synthesis requests

### Requirement: Health and Monitoring Integration
Each speech service SHALL expose a health endpoint and be integrated into the existing Prometheus/Grafana monitoring so degradation is observable without inspecting failed requests. The pinned STT model SHALL be resident at service start (no cold-load on first request).

#### Scenario: Degradation visible
- **WHEN** a speech container becomes unhealthy
- **THEN** monitoring reflects the state without a user-facing request having to fail first

#### Scenario: No cold start
- **WHEN** the first transcription request arrives after service start
- **THEN** it is served without model-load delay
