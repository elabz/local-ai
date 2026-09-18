# LiteLLM source patches

Files here are bind-mounted over modules inside the **digest-pinned** LiteLLM
image (`litellm/docker-compose.yml`). Each patch is written against that exact
image, so bumping the image digest means re-fetching the upstream file and
re-applying the patch. `gpu-server/tests/test_litellm_least_busy_patch.py` fails
until both are done.

## `least_busy.py` → `/usr/lib/python3.13/site-packages/litellm/router_strategy/least_busy.py`

The proxy runs `/usr/bin/litellm`, which imports from **site-packages**. The image
also has a source tree at `/app/litellm`, which `docker exec` finds first because
it starts in `/app`. Mounting there changes nothing: the first attempt did exactly
that and routing was unchanged.

`routing_strategy: least-busy` picks the deployment with the fewest in-flight
requests. Upstream (LiteLLM 1.81.9) keeps the *first* minimum it finds, so every
tie goes to the first replica in config order. HeartCode chat traffic is mostly
one request at a time, so nearly every request is a tie (all replicas idle). Over
24h on 2026-09-18 SFW chat split 1008 / 318 / 6 across gpu1/2/3, and GPU 1 sat at
85–87°C. The patch changes only `_get_available_deployments`:

- ties are broken uniformly at random, so idle traffic spreads evenly;
- only healthy deployments count, where upstream could pick a stale id and then fall back to random;
- negative counts, left by a decrement without a matching increment, read as 0.

Concurrent traffic still goes to the least-busy replica, as before.

`least_busy.upstream.py` is the unmodified file from the pinned image, kept for
diffing and re-applying:

```bash
ssh 192.168.70.152 'docker exec local-ai-litellm cat /usr/lib/python3.13/site-packages/litellm/router_strategy/least_busy.py' \
  > litellm/patches/least_busy.upstream.py
```
