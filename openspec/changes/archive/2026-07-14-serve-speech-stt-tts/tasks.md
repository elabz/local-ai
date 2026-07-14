# Tasks — serve-speech-stt-tts

## 1. Placement gate (blocks deployment)

- [x] 1.1 Stand up Kokoro-82M on dedicated GPU 7: validate CUDA execution on compute 6.1; record RTF, VRAM, and first-audio latency
- [x] 1.2 Stand up faster-whisper small / distil-small / large-v3-turbo (int8, fp32 fallback) on dedicated GPU 7: latency for 15/60/120s clips, VRAM, accuracy spot-check on conversational near-field speech
- [x] 1.3 Move restored GPU 2's chat/vision tenants off GPU 7; verify GPU 7 is empty and GPU 8 image generation remains isolated
- [x] 1.4 Kokoro concurrency probe (4 and 8 parallel syntheses) on chosen placement; decide replica count
- [x] 1.5 Record placement, chosen STT model, and all numbers in design.md; sync the numbers to heartcode `add-speech-gateway`

## 2. Containers

- [x] 2.1 Speaches service (compose entry, pinned always-loaded STT model, health endpoint, restart policy) at the gated placement
- [x] 2.2 Kokoro-FastAPI service with curated voicepacks; verify streaming chunked output directly against the container
- [x] 2.3 Verify STT/TTS inference is GPU-backed and no runtime silently falls back to CPU
- [x] 2.4 Wire both services into Prometheus/Grafana alongside existing gpu-server dashboards

## 3. LiteLLM

- [x] 3.1 Add `heartcode-stt` / `heartcode-tts` entries to `litellm/config.yaml`
- [x] 3.2 **Restart** the LiteLLM container on prod .152 (manual runbook; config is bind-mounted, `up -d` will not reload) and verify both models resolve via `/v1/models`
- [x] 3.3 Verify per-virtual-key accounting rows for speech requests
- [x] 3.4 Verify streaming audio passthrough (chunked `/v1/audio/speech`) end-to-end through LiteLLM; if broken, document the direct-call + dedicated-key exception and its accounting treatment in design.md

## 4. Validation & handoff

- [x] 4.1 Failure drills: stop Kokoro and Speaches in turn (typed 5xx, health red), then verify restart recovery
- [x] 4.2 nvidia-smi audit under speech load: chat/embedding GPUs untouched, speech confined to GPU 7, image generation confined to GPU 8
- [x] 4.3 Handoff to heartcode `add-speech-gateway` §3: endpoint URLs, model names, key setup, recorded gate numbers
