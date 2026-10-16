# Affinity and reuse-figure rollout (2026-10-16)

## LiteLLM on `.152`

- **Deployed:** `git pull` to bd0f21e, then `docker compose up -d litellm`. The compose file gained the `session_affinity.py` mount, so the container was recreated, not restarted.
  - Only this change's LiteLLM files were pending: `config.base.yaml`, `config.yaml`, `docker-compose.yml`, `patches/README.md`, `patches/least_busy.py` and `session_affinity.py`.
- **Healthy after the recreate:**
  - `/health/liveliness` 200;
  - the mounted `least_busy.py` defines `session_affinity_id`;
  - `/active/callbacks` lists `session_affinity.SessionAffinity`, next to `speech_correlation` and `public_api_guard`.

## Live check: `heartcode-chat-sfw`, the deployment from `x-litellm-model-id`

| Requests | Served by |
|---|---|
| 6 back to back, one session id | gpu2 gpu2 gpu1 gpu2 gpu2 gpu3 |
| 6 back to back, no session id | gpu1 gpu2 gpu2 gpu3 gpu2 gpu1 |
| 6 per session, 2 s apart, session 1 | gpu3 ×6 |
| 6 per session, 2 s apart, session 2 | gpu2 ×6 |
| 6 per session, 2 s apart, session 3 | gpu2 ×6 |

**Requests 2 s apart: 18/18 stayed on their replica.**

The back-to-back strays fit LiteLLM's in-flight bookkeeping:
- least-busy decrements a deployment's count in an async success callback that runs after the response is returned;
- a request sent within the same instant can still see the previous one as in flight, and goes to an idle sibling.

That is the "busier replica is never chosen" rule working as intended. Chat turns are seconds apart, since the user reads and types.

The first back-to-back session's home was gpu3, yet it went mostly to gpu2. So gpu3 most likely had another client's request in flight then: the dev stack's memory jobs share the route.

## Pea wrapper rollout (bind-mounted `routes.py` / `llama_client.py`)

- **First pass (bd0f21e):** one worker at a time, gated on peer health, the worker's own health, and a streamed request carrying `cached_tokens`.
  - `pea-gpu-3` passed.
  - `pea-gpu-6` failed the gate. Its usage chunk was present, but Lumimaid's llama-server reports reuse only in `timings.cache_n`, never in `usage.prompt_tokens_details`.
- **Fix (6cd056c):** the wrapper fills `cached_tokens` from `cache_n` when llama-server omits it. CI passed, including the image build.
- **Second pass (6cd056c):** OK for pea-gpu-6, 4, 5, 2, 1 and 3, between 19:08 and 19:17 UTC, each followed by a 60 s soak.
- **Deploy dry run afterwards:** clean for the chat workers. It lists `pea-speech-gpu-exporter` as `Recreate`, which is earlier drift unrelated to this change; audio work is parked, so it was left alone.

## End to end through LiteLLM (streamed, same session id, 2 s apart)

| Route | Turn 1 cached / prompt | Turn 2 cached / prompt |
|---|---|---|
| heartcode-chat-sfw | 1 / 36 | 31 / 36 |
| heartcode-chat-nsfw | 2 / 37 | 36 / 37 |

## Through HeartCode (dev stack, today's legacy layout, two consecutive turns)

`Prompt cache: route=heartcode-chat-sfw reused=1 evaluated=1333 first_answer=4.07s`, then `reused=1 evaluated=1334 first_answer=4.78s`. The admin endpoint shows the same: reuse 0.07%, mean first answer 4.42 s.

This is the baseline `stable-prompt-prefix` set out to record. Routing and reporting now work; the legacy prompt layout is what discards the cache on every turn.
