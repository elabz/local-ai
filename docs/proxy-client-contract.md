# Proxy client contract

Rules for anything that calls the LiteLLM proxy (`http://192.168.70.152:4000`).
They exist because every chat model group is a handful of single-slot GPU
replicas: `heartcode-chat-sfw` has 3 slots, `heartcode-chat-nsfw` has 3.
A client that ignores these rules does not get more throughput; it converts a
busy replica into an outage for everyone (see the 2026-08-27 → 09-16 NSFW
incident and the `queue-busy-chat-backends` change).

## What the proxy promises

| Signal | Meaning | What you do |
|---|---|---|
| `200` after a longer-than-usual wait | Your request queued for a busy slot (up to 60 s) and was served. This is normal. | Nothing. Show progress to the user if the wait matters. |
| `429` with body `BACKEND_BUSY` | Every replica in the group was busy for the whole admission window. Nothing is broken. | Back off and retry (below). Do not open a ticket. |
| `429` from the proxy itself (`max_parallel_requests` / RPM / TPM) | **Your key** is over its concurrency or rate cap. | You are fanning out too wide. Reduce concurrency; retry with backoff. |
| `503` (`GPU_UNAVAILABLE`, `BACKEND_UNAVAILABLE`, "no deployments available") | A backend is actually down or the whole group is in cooldown. | Retry with backoff; if it persists for minutes, page the operator. |
| `Retry-After: N` header | Present when a backend or the proxy can estimate when a slot frees. LiteLLM does **not** always forward the backend's header, so treat it as optional. | Wait at least `N` seconds before retrying when present. |

The proxy retries a busy or transiently failing replica on a sibling for you
(`num_retries: 2`). A `429` you see already means every sibling was tried.

## What you promise

1. **Bounded concurrency.** Never have more requests in flight to a model
   group than that group has slots (3 for each chat group today). Your key is
   capped at the proxy with `max_parallel_requests`; treat that as a ceiling,
   not a target. Interactive apps should run well under it.
2. **Batch consumers run a fixed, agreed worker count.** Backfills, re-embeds,
   bulk generation get a key capped at that count and must not run wider.
   Rediska is agreed at 4 parallel requests and its key is capped at 4.
3. **Honour `Retry-After`** when present. Otherwise use the backoff below.
4. **Jittered exponential backoff** on `429` and `503`:
   `sleep = min(60, base * 2**attempt) * uniform(0.5, 1.5)` with `base = 5 s`,
   at most 5 attempts, then surface the failure. Never retry in a tight loop,
   and never retry a request the user has abandoned.
5. **No fan-out to "find a free replica".** Sending the same prompt to several
   replicas (or several times to the proxy) to take the first answer occupies
   every slot with duplicate work. The proxy already load-balances
   (`least-busy`); one request per user action.
6. **Set a client timeout of at least 240 s** for chat. A queued request may
   wait 60 s and then generate for up to 180 s. A shorter client timeout
   abandons work the GPU still finishes, holding the slot for nobody.
7. **Stream when you can.** `stream: true` frees the connection sooner on the
   2-core host and lets you show progress; it does not change slot usage.
8. **One key per consumer.** Do not share a key between an interactive app
   and a batch job; the batch job will starve the app of its own cap.

## Reference: a compliant retry loop (Python)

```python
import random, time
import httpx

def chat(client: httpx.Client, payload: dict, attempts: int = 5) -> dict:
    for attempt in range(attempts):
        r = client.post("/v1/chat/completions", json=payload, timeout=240)
        if r.status_code < 400:
            return r.json()
        if r.status_code not in (429, 503) or attempt == attempts - 1:
            r.raise_for_status()
        retry_after = r.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else min(60, 5 * 2 ** attempt)
        time.sleep(delay * random.uniform(0.5, 1.5))
```

Run this behind a semaphore sized to your key's `max_parallel_requests`.

## Reference: slot counts (2026-09-16)

| Model group | Replicas / slots | Per-key cap ceiling |
|---|---|---|
| `heartcode-chat-sfw` (+ aliases) | 3 | 3 |
| `heartcode-chat-nsfw` (+ alias) | 3 | 3 |
| `heartcode-embed` | 2 | 2 |
| `heartcode-embed-vision` | 2 | 2 |
| `heartcode-embed-visual` | 2 | 2 |
| `heartcode-image` | 2 | 2 |

A key's `max_parallel_requests` must not exceed the sum of the slot counts of
the groups it may call. See the key-generation procedure in `CLAUDE.md`
("API Key Management") and `litellm/scripts/cap-key-concurrency.py`.

## Applies to

Chat, embeddings, image, STT and TTS routes alike. The admission queue and
`429 BACKEND_BUSY` semantics are implemented on the chat wrappers today; the
backoff and concurrency rules apply to every route.
