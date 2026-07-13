## Context

Companion infra change for HeartCode's `add-speech-gateway` (see that change's proposal/design for engine research and product motivation). Fleet reality: PEA has 8x P104-100 (Pascal, compute 6.1, 8GB, no tensor cores), 7 usable; GPUs 1–3 SFW chat, 4–7 NSFW chat (per current layout), GPU 8 runs SSD-1B image gen on `:5100`; LiteLLM proxy on prod `.152:4000` with PostgreSQL-backed virtual keys. Engine selection was settled in the HeartCode change: faster-whisper (STT), Kokoro-82M primary + Piper CPU fallback (TTS).

## Goals / Non-Goals

**Goals:**
- `heartcode-stt` and `heartcode-tts` callable through LiteLLM with per-key accounting, exactly like chat models.
- Streaming TTS output verified end-to-end through the proxy path.
- Placement (GPU-8 slice vs CPU) committed from measurements recorded in this change.
- Health/monitoring parity with existing gpu-server services.

**Non-Goals:**
- No voice catalog, audio storage, chat integration, or UI (HeartCode).
- No streaming-STT WebSocket server (WhisperLive) yet — deployed later only if HeartCode's `add-voice-conversation` latency gate demands it.
- No changes to chat-model GPU allocation; no use of the faulty card (GPU-f1fa6009).

## Decisions

### Decision 1: Off-the-shelf OpenAI-compatible containers, not custom wrappers
Speaches (STT), Kokoro-FastAPI (TTS), openedai-speech (Piper) are maintained projects already speaking the OpenAI audio API. Rationale: the custom gpu-server wrapper has bitten us before (it silently drops sampler params); for speech we adopt upstream servers wholesale and keep our surface to compose files + LiteLLM config. Alternative (extend `gpu-server/` façade) rejected for that reason.

### Decision 2: Candidate placements and the gate
Measured candidates: (a) GPU-8 slice colocated with SSD-1B, (b) PEA CPU, (c) HeartCode backend-host CPU (would move containers out of this repo's host — only if PEA CPU fails). Gate metrics: STT latency for 15/60/120s clips, TTS RTF + first-audio latency, VRAM, SSD-1B latency delta under colocated speech load, and Kokoro throughput at 4/8 concurrent syntheses. Numbers land in this file; compose placement follows them.

### Decision 3: LiteLLM as the single routing surface, with a documented escape hatch
Both models register in `litellm/config.yaml`. Known gotcha: the config is bind-mounted and requires a container **restart** (never just `up -d`). Streaming chunked audio through LiteLLM must be verified explicitly; if broken, HeartCode calls the speech containers directly with a dedicated key and LiteLLM keeps registration for accounting only — the exception and its accounting story get documented here.

### Decision 4: Model pinning over dynamic loading
Speaches supports load-on-demand; we pin the chosen whisper model always-loaded to avoid cold-start latency in interactive flows. Kokoro's single small model is always resident.

## Risks / Trade-offs

- [Kokoro ONNX CUDA EP fails on compute 6.1] → CPU placement measured in the same gate is faster-than-real-time on paper; Piper is the second net.
- [Colocation degrades SSD-1B latency] → gate measures the delta; regression beyond tolerance ⇒ CPU placement.
- [LiteLLM audio passthrough gaps] → Decision 3 escape hatch.
- [Prod `.152` write restrictions] → LiteLLM config edits + restart follow the existing manual runbook for prod changes (same as pending prod restart workflow).

## Open Questions
- Final whisper model (small vs distil-small vs large-v3-turbo int8) — gate decides on accuracy/latency for near-field conversational speech.
- Kokoro replica count — from the concurrency probe.
