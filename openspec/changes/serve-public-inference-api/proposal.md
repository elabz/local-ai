# Serve HeartCode's Public Inference API

## Why

HeartCode's `harden-public-inference-api` makes the public OpenAI-compatible
API LiteLLM-native: SillyTavern and similar clients call this proxy directly
with HeartCode-minted virtual keys. Two things on this side stopped that from
being a working, bounded backend (measured 2026-10-10 against the live fleet,
reading llama.cpp's `/slots` for what each generation actually used):

1. **The Pea wrapper dropped OpenAI-format fields.** `ChatCompletionRequest`
   had no `stop`, `seed`, `presence_penalty`, `frequency_penalty` or
   `repetition_penalty`, so pydantic discarded them. A request with
   `stop: ["7"]` counted straight past 7, direct and through LiteLLM. Stop
   strings are how roleplay clients keep the model from writing the user's
   turn. `temperature`, `top_p`, `top_k`, `min_p`, `max_tokens` and
   `repeat_penalty` did arrive, overriding the deployment defaults.
2. **Nothing bounded the public keys as a group.** Per-key `rpm`/`tpm`/
   `max_parallel_requests` bound one key; team-level `max_parallel_requests`
   is not enforced by LiteLLM 1.81.9 (a team capped at 1 admitted three
   concurrent requests). Chat capacity is five llama.cpp slots in total (three
   SFW, two NSFW, `--parallel 1` each), shared with HeartCode's own chat, and
   there was no message-size, message-count, sampler or `max_tokens` bound.

## What Changes

- Wrapper (`gpu-server/routes.py`, `llama_client.py`): accept and forward
  `stop` (string or list), `seed`, `presence_penalty`, `frequency_penalty`,
  and `repetition_penalty` as llama.cpp's `repeat_penalty` (the llama.cpp
  spelling wins when both are sent), on both chat paths.
- New LiteLLM callback `litellm/public_api_guard.py`, for keys whose metadata
  carries `heartcode_key_name` only: reject more than 100 messages or a
  message over 32 KiB (413), clamp samplers and `max_tokens` (ceiling 1024,
  applied when unsent too), force `n` to 1, and admit one public generation
  per chat model group at a time (429 with `Retry-After`), so first-party chat
  keeps two of three SFW slots and one of two NSFW slots.
- Limits are compose environment (`PUBLIC_API_*`) with those defaults.

## Capabilities

### New Capabilities
- `public-inference-gateway`: OpenAI-format sampler fields reach llama.cpp;
  HeartCode public keys are bounded in size, samplers and shared concurrency.

### Modified Capabilities
_None._

## Impact

- Pea: the wrapper is baked into `local-ai-llama`; the chat slots need a
  rebuild and a rolling restart to pick it up.
- elm: `public_api_guard.py` is bind-mounted and registered in
  `config.base.yaml`; LiteLLM needs `restart`, not `up -d`.
- First-party traffic (HeartCode's backend key, rediska, health checks) is
  untouched: the guard matches only the HeartCode public-key marker.
- HeartCode companion: `harden-public-inference-api` tasks 1.3, 1.5 and 1.6.
