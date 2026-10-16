# GPU fault readiness and PCI-path triage

GPU-backed HTTP services fail closed when `GPU_HEALTH_ENABLED=1`. `/live` only
proves that the process can answer HTTP. `/health` proves the configured GPU is
the visible device, its memory can be queried, the model is loaded, and (for
Torch services) a small synchronized CUDA operation succeeds. A failed check
returns HTTP 503 and inference is rejected before model work begins. Recovery
requires two consecutive complete checks.

The deployed LiteLLM 1.81.9 active checker performs a bounded synthetic
OpenAI request rather than calling a configurable backend health URL. GPU
admission must therefore run before parsing or model invocation: its 503 is
the signal that removes the deployment from LiteLLM rotation. Reconfirm this
behavior after every LiteLLM image upgrade because the compose tag currently
uses `main-latest`.

DINO deployments declare the dedicated LiteLLM health model
`openai/heartcode-embed-visual-health`. Only that exact model combined with
LiteLLM's bounded health input is accepted as text, after GPU readiness has
passed. Normal DINO text requests remain invalid.

If a configured UUID disappears completely, NVIDIA CDI can reject container
startup before the HTTP application runs. This is fail-closed but yields a
connection failure rather than `/health` 503. Do not weaken device placement
to make the endpoint start; keep the deployment excluded and perform host or
physical-path recovery. A GPU-independent quarantine endpoint would be a
separate design change.

## PCI 04:00.0 incident evidence

Two distinct boards have failed at the same physical PCI address:

- `GPU-f1fa6009-d240-3810-d6ca-4c65ecc22dcf` failed initialization at
  `04:00.0` with VBIOS-copy and `RmInitAdapter` errors. Commit `bb81f452`
  records moving its tenants away; a reboot later restored all eight cards.
- Its replacement, `GPU-8d0782cb-a2e0-dcbb-da61-63e16d950e77`, was assigned
  the same `04:00.0` path (recorded by commit `cab1fe4`) and later emitted Xid
  79 (fallen off bus) with an AER physical-receiver error.

This repetition strongly implicates the slot, riser, ASM1184e switch lane,
connector, or power delivery serving `04:00.0`; it does not by itself prove
which component is defective or exclude two independent board failures.

## PCI 0a:00.0 replacement (2026-10-16)

`GPU-d8525241-21cb-a127-b4d8-d72b9ac32b1b` (slot `gpu-5`, `nvidia-smi` index 4)
was replaced by `GPU-62676508-8e4e-f040-6515-135a0b906ed1` at the same address.

- History of the failed board: 1,821 Xid faults, all on `0a:00` (13, 43 and
  31 MMU faults; the last on 2026-07-25). Corrupt generation above ~7.6 GiB
  (2026-09-04), at ~6.6 GiB (2026-09-19, pulled from `heartcode-chat-nsfw`),
  then from ~1.1k prompt tokens at greedy decoding (2026-10-16). The image,
  model file and flags matched the healthy NSFW replicas, so only the card
  differed. The co-located text embedder stayed correct (cosine 1.000 against
  `pea-embed-4`).
- Found in the chassis by heat: 4 minutes of load on `:8084` alone took the
  card to 81 C while the others sat at 30-46 C.
- After power-up the controller adopted the new UUID ("Adopted replacement for
  gpu-5 at 0000:0a:00.0") and recreated `pea-gpu-5` and `pea-embed-5` on it.
  Acceptance: no Xid this boot; greedy replies identical to `:8085` at 632 to
  8,252 prompt tokens; embeddings identical to `pea-embed-4`. `:8084` returned
  to `heartcode-chat-nsfw` and the quarantine record was removed.

## Safe response

1. Confirm the affected service returns 503 from `/health` but 200 from
   `/live`, and confirm its sibling remains ready. Do not send a model request
   merely to test a known-failed CUDA context.
2. Record only the service name, configured GPU UUID, PCI address, bounded
   readiness reason, Xid/AER code, and timestamps. Never capture prompts,
   images, embeddings, credentials, full environments, or attestations.
3. Verify the router has cooled down the failed deployment. If it has not,
   remove that deployment from the model list before physical work.
4. Drain or stop workloads on the affected physical path. Inspect and reseat
   the card, riser, auxiliary power, and upstream switch connections with the
   host powered down. Swap one component/path at a time so the result is
   attributable.
5. After power-up, require stable enumeration, clean kernel logs, two complete
   readiness successes, and a bounded synthetic inference before restoring
   traffic. Watch readiness transitions and AER/Xid logs during load.

## Rollback

The rollout gate defaults off. Set `GPU_HEALTH_ENABLED=0` and recreate only the
affected replica to revert application gating. This is a software rollback,
not permission to route traffic to a GPU with Xid, AER, identity, memory, or
execution failures. If readiness code cannot be deployed safely to a failed
replica, remove that replica from LiteLLM until the host has been power-cycled
and the physical path has passed the checks above.
