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
