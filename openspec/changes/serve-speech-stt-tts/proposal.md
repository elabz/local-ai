# Serve Speech STT + TTS (heartcode-stt / heartcode-tts)

## Why

HeartCode is building a voice feature series (dictation → voice notes → hands-free voice calls; see `heartcode:openspec/changes/add-speech-gateway`, which this change is the infra half of). Those features need self-hosted speech inference served over the same OpenAI-compatible/LiteLLM surface as chat. This repo's job is to **serve** STT and TTS models; product behavior, audio storage, and chat integration live downstream in HeartCode.

## What Changes

- **Serve STT** behind `heartcode-stt`: a **Speaches** container (faster-whisper / CTranslate2 backend — FP32 fallback works on Pascal compute 6.1) exposing OpenAI `/v1/audio/transcriptions`, with the chosen whisper model (small-class int8; final pick from the placement gate) pinned always-loaded.
- **Serve TTS** behind `heartcode-tts`: a **Kokoro-FastAPI** container (Kokoro-82M, Apache/MIT, FP32-native, streaming chunked audio output) as primary, plus an **openedai-speech (Piper, CPU)** container as the fallback tier.
- **Placement gate before deployment**: benchmark both runtimes on a P104 slice (colocated with SSD-1B on GPU 8) vs PEA CPU vs measured impact on image-generation latency; commit placement from numbers, never assumption. Chat-model GPUs are off-limits.
- **LiteLLM wiring**: register `heartcode-stt` / `heartcode-tts` in `litellm/config.yaml` (container **restart** required — config is bind-mounted and never reloads on `up -d`); verify streaming audio passthrough; document direct-call exception if LiteLLM can't proxy chunked audio bodies.
- **Monitoring**: health endpoints scraped by Prometheus/Grafana alongside the existing gpu-server dashboards.

## Capabilities

### New Capabilities
- `speech-serving`: serve OpenAI-compatible STT (`/v1/audio/transcriptions`) and streaming TTS (`/v1/audio/speech`) via LiteLLM as `heartcode-stt`/`heartcode-tts`, with measured Pascal/CPU placement, an engine fallback tier, and health/monitoring integration. Serving only; voice catalogs, storage, and chat behavior are downstream (HeartCode).

### Modified Capabilities
_None (no established spec in `openspec/specs/` covers speech)._

## Impact

- **Containers**: new `speech/` services (Speaches, Kokoro-FastAPI, openedai-speech) in this repo's compose layout; placement (GPU-8 slice vs CPU) decided by the gate.
- **LiteLLM**: two new model entries + restart; virtual-key accounting extends to speech automatically.
- **GPU layout**: at most a slice of GPU 8 (image GPU) is a candidate; GPUs 1–7 (chat) untouched; GPU-f1fa6009 remains out of service.
- **Downstream contract**: HeartCode's `add-speech-gateway` consumes the endpoints and the gate's recorded numbers; its section-2 tasks point here.
- **Licenses**: faster-whisper/CTranslate2 MIT; Kokoro Apache/MIT; Piper GPL — isolated as a network service, no code linkage.
