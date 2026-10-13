## ADDED Requirements

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
