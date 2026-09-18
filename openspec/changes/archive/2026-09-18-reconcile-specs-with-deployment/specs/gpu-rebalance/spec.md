## REMOVED Requirements

### Requirement: Image generation load-balanced across two GPUs
**Reason**: GPU 7 was reassigned to speech by `serve-speech-stt-tts` (2026-07-14); only one image server runs, and `models.yaml` declares `min_replicas: 1`.
**Migration**: Replaced by "Image generation served from GPU 8". A second image server returns only through a manifest change that raises `min_replicas`.

## ADDED Requirements

### Requirement: Image generation served from GPU 8

The system SHALL run one image-generation server on GPU 8 behind `heartcode-image`; GPU 7 is dedicated to speech. The image server SHALL keep its installed cuda12-diffusers backend and SSD-1B model on persistent volumes so that a restart does not re-download them. Adding a second image server SHALL be a manifest change that raises `min_replicas` in the same edit.

#### Scenario: Image request is served
- **WHEN** an image-generation request arrives at `heartcode-image`
- **THEN** it is served by the GPU 8 image server

#### Scenario: Restart reuses installed backend
- **WHEN** the image server restarts
- **THEN** it uses the already-installed cuda12-diffusers backend and SSD-1B model from the persistent volumes rather than re-downloading them
