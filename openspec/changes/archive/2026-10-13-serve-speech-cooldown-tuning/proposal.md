# Proposal: serve-speech-cooldown-tuning

## Why

`heartcode-stt` and `heartcode-tts` each have exactly one LiteLLM deployment, and Pea's 2-core host rules out replicas. Today they run under the router's global settings: `allowed_fails: 3`, `cooldown_time: 20`, `num_retries: 2`, `retry_after: 3`. Those were tuned in `queue-busy-chat-backends` for chat groups that have siblings to route to.

For a group with one deployment, a cooldown has nowhere to send traffic. It turns three errors into a 20-second outage of all transcription. That cuts every live call off mid-turn.

This happened on 2026-09-09. Under the old settings, one STT 500 cooled the sole deployment, and every later transcription returned 429 until the cooldown expired. `queue-busy-chat-backends` stopped *busy* responses from cooling deployments, but real errors still can.

The 3-second retry delay is also longer than HeartCode's whole retry budget for a speech operation (`SPEECH_RETRY_DEADLINE_SECONDS` = 2.0). A retry inside LiteLLM therefore only makes the caller's turn late, never successful.

This is the companion that HeartCode's `add-speech-admission-control` (task 8.1) asks for. Per the cross-repo pattern, HeartCode drives and local-ai serves.

## What Changes

- **A sole speech deployment is never cooled down.** For `heartcode-stt` and `heartcode-tts`, an error is returned to the caller, which handles it (HeartCode retries with jitter inside its deadline and then reports busy). It never removes the only route.
- **Speech fails fast.** Speech groups get at most one immediate retry, with no fixed 3-second delay, so a LiteLLM retry fits inside HeartCode's 2-second budget or is not attempted.
- **The mechanism is verified on the pinned LiteLLM image before it is relied on.** That covers per-deployment `cooldown_time`, per-group retry policy, or the router's own single-deployment handling. The existing routing integration test gains single-deployment speech cases.
- **The settings are authored in the sources** (`gpu-server/models.yaml` `params`, `litellm/config.base.yaml`), regenerated, and applied with a LiteLLM `restart` on elm. The generated `config.yaml` is never hand-edited.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `speech-serving`: adds the single-deployment cooldown and fail-fast requirement for the speech groups.

## Impact

- `gpu-server/models.yaml`: `params` on the two speech entries.
- Possibly `litellm/config.base.yaml`: a group-scoped retry policy, if per-deployment params cannot express it.
- `gpu-server/scripts/render-config.py`: only if the generator must pass a new key through.
- `gpu-server/tests/integration/test_litellm_gpu_routing.py` and its fake backend: new single-deployment cases.
- An operator `restart` of LiteLLM on elm.
- HeartCode is unaffected until it lands. Afterwards, HeartCode reruns its 7.1 load check (task 8.2 there) to see whether the retry rate changed.

## Non-goals

- **Speech capacity.** Replicas cannot add throughput on a 2-core host (HeartCode `add-speech-admission-control` Decision 8).
- **RPM caps sized from load measurements, and a `heartcode-tts-128k` route.** These belong to the companion that HeartCode's `trial-live-speech-via-litellm` (task 3.1) will open once its load pass (4.2) has measured them. This change takes only the cooldown and fail-fast part of that list. Both changes edit the same entries, so whichever lands second rebases.
- **Chat groups.** Their cooldown behaviour, with siblings to route to, stays as `queue-busy-chat-backends` set it.
