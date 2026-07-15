# HeartCode speech runtime operations

## Deployment and health gates

1. Provision `SPEECH_DIRECT_API_KEY` in the PEA and HeartCode backend secret stores. Provision LiteLLM's copy only when its TTS model route uses the authenticated PEA edge.
2. Deploy `speech-stt` and `speech-tts`; wait for both model-aware health checks to pass.
3. Deploy `speech-meter`, `speech-gpu-exporter`, `speech-stream-gateway`, `blackbox-exporter`, Prometheus, and Grafana.
4. Recreate Prometheus after replacing bind-mounted configuration files. Confirm the `speech-health`, `speech-requests`, and `speech-gpu` targets are up.
5. Deploy the LiteLLM `speech_correlation.py` callback and configuration, then recreate LiteLLM so the read-only callback mount is refreshed.
6. Run `controlled_probe.sh`. Do not enable HeartCode traffic unless it reports two 2xx routes, two correlated meter log entries, an exact LiteLLM accounting row, the expected GPU UUID/index, non-zero process memory, and an increased speech request counter.
7. Enable normal STT/TTS through LiteLLM first. Enable backend-only direct TTS streaming after the authenticated route passes independently. Browsers never receive the direct service credential.

`SPEECH_TTS_ENCODING_PROFILE` selects the live Ogg/Opus profile. Supported values are `opus-128k`, `opus-48k`, `opus-40k`, and `opus-32k`; the accepted default is `opus-40k`. The controlled probe sends the configured profile and rejects a response without an Ogg container signature. Lower profiles transcode provider PCM incrementally with 24 kHz mono libopus; MP3 preview traffic remains provider-native and is unaffected.

## Measured baseline and alerts

On 2026-07-14, controlled warm samples measured p95 near 0.49s for both operations; earlier cold samples measured up to 1.9s STT and 0.85s TTS. No request failures were observed. Warning thresholds are therefore 4s STT and 2s TTS for 15 minutes, and greater than 5% errors for 10 minutes with at least ten requests. Re-measure after model, GPU, driver, or provider changes.

## Evidence and retention

Sanitized probe JSON belongs in `speech/evidence/`. It contains IDs, HTTP status, accounting-row count, low-cardinality counter deltas, and GPU placement/residency—never keys, authorization headers, audio, transcripts, prompts, or synthesized audio. Retain probe evidence for 30 days, matching Prometheus retention, unless the incident policy requires longer. Gateway/container logs use the platform log rotation policy and must not be exported without the same redaction rules.

## Rollback

1. For an encoding-only rollback, set `SPEECH_TTS_ENCODING_PROFILE=opus-128k` in PEA and HeartCode, recreate `speech-meter` and the HeartCode backend, then run `controlled_probe.sh`. This bypasses the added encoder and restores the pinned provider's prior Opus output.
2. Disable HeartCode's direct TTS feature flag and route STT/TTS away from the new deployment if the profile rollback is insufficient.
3. Restore the previous LiteLLM config and recreate LiteLLM.
4. Stop the gateway, meter, exporter, STT, and TTS services. Preserve `speech-model-cache` and the secret so a rollback can be reversed without downloading models again.
5. Leave unrelated GPU workloads, Prometheus data, and model caches untouched.

## Secret rotation

Generate a new high-entropy direct key, update PEA and HeartCode secret stores, recreate the gateway, validate the new key, then revoke the old value. Never place either value in Git, compose arguments, evidence, logs, browser code, or frontend configuration. Rotate immediately after suspected exposure and on the normal service-secret schedule.
