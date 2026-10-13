# Tasks: serve-speech-cooldown-tuning

## 1. Establish the pinned image's behaviour

- [x] 1.1 In `gpu-server/tests/integration/`, add a single-deployment group to `litellm_gpu_routing.yaml` backed by `fake_openai_backend.py`, and have the fake return 500 on demand. Record what LiteLLM 1.81.9 does under today's global settings after three 500s: does the fourth request reach the backend, or get a cooldown 429, and for how long?
- [x] 1.2 Repeat with each mechanism from design Decision 1, in order:
  - (a) `cooldown_time: 0` in the deployment's `litellm_params`;
  - (b) no change, if 1.1 shows the router already skips single-deployment cooldown;
  - (c) a group-scoped policy in `config.base.yaml`.

  Keep the first that passes, and record the result in `design.md`.
- [x] 1.3 Likewise for retries: find whether the pinned version honours a per-group or per-deployment retry count and delay (Decision 2). Choose `num_retries: 1` with no delay, or 0.

## 2. Author the settings

- [x] 2.1 Add the chosen keys to the `heartcode-stt` and `heartcode-tts` entries' `params` in `gpu-server/models.yaml`. Touch `config.base.yaml` only for option (c). Extend `render-config.py` only if a key does not pass through.
- [x] 2.2 Regenerate `litellm/config.yaml`; `validate_config.py` and the CI config check pass.
- [x] 2.3 Turn the 1.x cases into permanent assertions in `test_litellm_gpu_routing.py`, and confirm chat groups still cool down after three failures, as before. *(Done as a static check: chat deployments carry no override. The pinned image does not cool chat on errors at all, before or after; see design.md, 2.3 finding.)*

## 3. Apply on elm (operator)

- [ ] 3.1 Pull on elm and `docker compose restart litellm`. A restart is required: the bind-mounted config does not reload on `up -d`.
- [ ] 3.2 Verify with `/v1/model/info` under the master key that the speech deployments carry the new `litellm_params`.
- [ ] 3.3 Run one transcription and one synthesis through LiteLLM with a HeartCode key; both succeed.

## 4. Close the loop with HeartCode

- [ ] 4.1 Tell HeartCode it landed. Its `add-speech-admission-control` 8.2 reruns the 7.1 load check (`backend/scripts/benchmark_concurrent_calls.py`) and records whether the retry rate changed. Its `trial-live-speech-via-litellm` 3.1 companion rebases on these entries.
