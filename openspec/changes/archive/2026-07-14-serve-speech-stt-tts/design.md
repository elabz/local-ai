## Context

Companion infra change for HeartCode's `add-speech-gateway` (see that change's proposal/design for engine research and product motivation). Fleet reality as of 2026-07-13: PEA has 8 healthy P104-100 cards (Pascal, compute 6.1, 8GB, no tensor cores) and a weak two-core Celeron CPU reserved for orchestration. GPUs 1–3 serve SFW chat plus visual embeddings, GPUs 4–6 serve NSFW chat plus text/DINO embeddings, dedicated GPU 7 (zero-based index 6, UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988`) is reserved for speech, and GPU 8 runs SSD-1B image generation on `:5100`. LiteLLM runs on prod `.152:4000` with PostgreSQL-backed virtual keys. Engine selection is faster-whisper (STT) and Kokoro-82M (TTS), with no CPU inference fallback.

## Goals / Non-Goals

**Goals:**
- `heartcode-stt` and `heartcode-tts` callable through LiteLLM with per-key accounting, exactly like chat models.
- Streaming TTS output verified end-to-end through the proxy path.
- Dedicated GPU-7 capacity and compatibility committed from measurements recorded in this change.
- Health/monitoring parity with existing gpu-server services.

**Non-Goals:**
- No voice catalog, audio storage, chat integration, or UI (HeartCode).
- No streaming-STT WebSocket server (WhisperLive) yet — deployed later only if HeartCode's `add-voice-conversation` latency gate demands it.
- The restored GPU 2 takes back its SFW chat and vision-embedding tenants; no speech workload may use chat, embedding, or image-generation GPUs.

## Decisions

### Decision 1: Off-the-shelf OpenAI-compatible containers, not custom wrappers
Speaches (STT) and Kokoro-FastAPI (TTS) are maintained projects already speaking the OpenAI audio API. Rationale: the custom gpu-server wrapper has bitten us before (it silently drops sampler params); for speech we adopt upstream servers wholesale and keep our surface to compose/routing configuration plus the small model-residency healthcheck. Alternative (extend `gpu-server/` façade) rejected for that reason.

### Decision 2: Dedicated GPU placement and the gate
Both engines run only on dedicated PEA GPU 7. Gate metrics: STT latency for 15/60/120s clips, TTS RTF + first-audio latency, VRAM, and Kokoro throughput at 4/8 concurrent syntheses. Numbers land in this file. CPU inference comparisons and the former SSD-1B colocation test are removed: the Celeron is too weak for production inference and GPU 8 remains isolated from speech.

### Decision 3: LiteLLM as the single routing surface, with a documented escape hatch
Both models register in `litellm/config.yaml`. Known gotcha: the config is bind-mounted and requires a container **restart** (never just `up -d`). Streaming chunked audio through LiteLLM must be verified explicitly; if broken, HeartCode calls the speech containers directly with a dedicated key and LiteLLM keeps registration for accounting only — the exception and its accounting story get documented here.

### Decision 4: Model pinning over dynamic loading
Speaches supports load-on-demand; we pin the chosen whisper model always-loaded to avoid cold-start latency in interactive flows. Kokoro's single small model is always resident.

## Measured placement and production result (2026-07-13)

All measurements ran on a P104-100 (Pascal compute 6.1) with both CUDA services sharing the candidate card. No CPU inference image was deployed.

| Probe | Result |
|---|---|
| Kokoro CUDA initialization | Passed; model warmup explicitly reported `CUDA: True` |
| Kokoro warmup | 10.88 s |
| Kokoro representative ~10.9 s utterance | 0.81 s total, 73 ms first bytes, RTF ~0.074 |
| Kokoro concurrency 4 | 2.47 s wall time; individual totals 1.83–2.41 s |
| Kokoro concurrency 8 | 4.87 s wall time; one 0.63 s completion, remaining totals 4.80–4.82 s |
| faster-whisper small.en, 15/60/120 s | 1.67 / 3.55 / 6.45 s; exact synthetic transcript content |
| faster-whisper large-v3-turbo, 15/60/120 s | 1.87 / 4.11 / 7.10 s; no accuracy advantage on the sample |
| Systran distil-small | Rejected: current Speaches image hits a model-card metadata assertion during transcription |
| Production combined VRAM during end-to-end request | ~1.34 GiB; ~1.78 GiB observed during long concurrent synthesis |

Committed model: `guillaumekln/faster-whisper-small.en` with CTranslate2 `int8`. One Kokoro replica is sufficient initially. Production placement is dedicated GPU 7, UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988`. GPU 2's restored chat/vision tenants are healthy on UUID `GPU-8d0782cb-a2e0-dcbb-da61-63e16d950e77`; the image service remains isolated on GPU 8.

## Endpoints, streaming, and accounting

- Accounted STT: `POST http://192.168.0.152:4000/v1/audio/transcriptions`, model `heartcode-stt`.
- Accounted non-streaming TTS: `POST http://192.168.0.152:4000/v1/audio/speech`, model `heartcode-tts`.
- Low-latency streaming TTS: `POST http://192.168.0.144:8201/v1/audio/speech`, model `kokoro`, using `Authorization: Bearer $SPEECH_DIRECT_API_KEY`.
- Direct Speaches/Kokoro health inside PEA: `:8200/health` and the internal `speech-tts:8880/health`; Prometheus exposes both as `probe_success{job="speech-health"}`.

LiteLLM successfully proxies both audio endpoints and writes virtual-key accounting rows (two rows verified with a short-lived speech-only key). It buffers TTS bodies: a long direct request delivered first bytes in 8 ms and completed in 10.75 s, while LiteLLM delivered first bytes at 10.45 s and completed at 10.45 s. Therefore interactive streaming uses the authenticated Caddy gateway on `:8201` with buffering disabled. Those direct calls are not LiteLLM spend rows; they are separated by the dedicated key and recorded in the gateway's structured access log. Requests that require LiteLLM virtual-key accounting use the proxy path and accept full-body buffering.

Failure drills passed: stopped TTS returned gateway 502 and LiteLLM 500, stopped STT returned a JSON LiteLLM connection error, and both services recovered healthy with the STT model resident. Unauthorized direct TTS calls return 401.

## Risks / Trade-offs

- [Kokoro CUDA path fails on compute 6.1] → deployment blocks while a GPU-compatible Kokoro runtime is selected; never silently fall back to CPU.
- [Restored-card migration is not active] → verify live UUID-to-container placement and leave speech stopped until GPU 7 is empty.
- [LiteLLM buffers streaming audio] → measured and handled by the authenticated non-buffering `:8201` direct gateway documented above.
- [Prod `.152` write restrictions] → LiteLLM config edits + restart follow the existing manual runbook for prod changes (same as pending prod restart workflow).

## Open Questions
- Final whisper model (small vs distil-small vs large-v3-turbo int8) — gate decides on accuracy/latency for near-field conversational speech.
- Kokoro replica count — from the concurrency probe.
