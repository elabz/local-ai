## Why

The `project-health-improvements` triage (2026-09-18) found a main-spec requirement that no longer matches the deployment. `gpu-rebalance` still requires two image servers on GPU 7 and GPU 8, but GPU 7 was given to the speech stack by `serve-speech-stt-tts` (2026-07-14). Only `pea-image-1` on GPU 8 runs, `models.yaml` declares `heartcode-image` with `min_replicas: 1`, and `speech-serving` already states that GPU 8 is exclusive to image generation. This change corrects the spec to match reality; it changes nothing deployed.

## What Changes

- Modify the `gpu-rebalance` requirement "Image generation load-balanced across two GPUs" so it describes the single image server on GPU 8 by removing the two-server requirement and adding a one-server requirement.

## Capabilities

### New Capabilities

### Modified Capabilities
- `gpu-rebalance`: the image-generation requirement now describes one server on GPU 8 instead of two on GPU 7 and GPU 8.

## Impact

Spec text only. No code, config or host changes.
