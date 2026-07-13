# Tasks — serve-speech-stt-tts

## 1. Placement gate (blocks deployment)

- [ ] 1.1 Stand up Kokoro-82M (ONNX Runtime) on a GPU-8 slice: CUDA EP load on compute 6.1; RTF, VRAM, first-audio latency vs PEA CPU on identical texts
- [ ] 1.2 Stand up faster-whisper small / distil-small / large-v3-turbo (int8, fp32 fallback) on GPU-8 slice vs CPU: latency for 15/60/120s clips, VRAM, accuracy spot-check on conversational near-field speech
- [ ] 1.3 SSD-1B latency baseline vs under colocated speech load on GPU 8; record tolerance verdict
- [ ] 1.4 Kokoro concurrency probe (4 and 8 parallel syntheses) on chosen placement; decide replica count
- [ ] 1.5 Record placement, chosen STT model, and all numbers in design.md; sync the numbers to heartcode `add-speech-gateway`

## 2. Containers

- [ ] 2.1 Speaches service (compose entry, pinned always-loaded STT model, health endpoint, restart policy) at the gated placement
- [ ] 2.2 Kokoro-FastAPI service with curated voicepacks; verify streaming chunked output directly against the container
- [ ] 2.3 openedai-speech (Piper) CPU fallback service, independently addressable
- [ ] 2.4 Wire all three into Prometheus/Grafana alongside existing gpu-server dashboards

## 3. LiteLLM

- [ ] 3.1 Add `heartcode-stt` / `heartcode-tts` entries to `litellm/config.yaml`
- [ ] 3.2 **Restart** the LiteLLM container on prod .152 (manual runbook; config is bind-mounted, `up -d` will not reload) and verify both models resolve via `/v1/models`
- [ ] 3.3 Verify per-virtual-key accounting rows for speech requests
- [ ] 3.4 Verify streaming audio passthrough (chunked `/v1/audio/speech`) end-to-end through LiteLLM; if broken, document the direct-call + dedicated-key exception and its accounting treatment in design.md

## 4. Validation & handoff

- [ ] 4.1 Failure drills: stop Kokoro (Piper reachable), stop Speaches (typed 5xx, health red), restart recovery
- [ ] 4.2 nvidia-smi audit under speech load: chat GPUs untouched, GPU-8 usage within gate numbers
- [ ] 4.3 Handoff to heartcode `add-speech-gateway` §3: endpoint URLs, model names, key setup, recorded gate numbers
