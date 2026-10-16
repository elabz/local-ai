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
