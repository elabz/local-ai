# Proposal: restore-nsfw-chat-capacity

## Why

`heartcode-chat-nsfw` has been served by a single replica (GPU 4, one slot, zero admission wait) since the NSFW replicas on GPUs 5 and 6 were removed from routing on 2026-08-27 for the model canaries. Any second concurrent NSFW request is rejected with 503, LiteLLM cools the only deployment for 90 s, and every consumer sees 429. Rediska's lead pipeline produced zero successful inferences for three weeks as a result. Meanwhile GPU 5 holds only the 234 MiB text-embed process because the SFW canary was pinned to GPU 6, and the repo's topology, compose comments and models.yaml all describe the opposite placement.

## What Changes

- Restore the NSFW chat replica `gpu-server-5` (`pea-gpu-5`, port 8084) on GPU 5 at the production Lumimaid Q5_K_M configuration, which allocates ~6.4 GiB and stays ~1.2 GiB below the card's documented ~7.6 GiB generation-corruption region. Restoration is gated on a repeated-coherent-generation check on the restored replica, not on a successful model load.
- Route the replica again: add `{gpu: 5, port: 8084}` to the `heartcode-chat-nsfw` deployments in `models.yaml`, and re-add the already-running, unrouted text-embed replica `{gpu: 5, port: 8094}` to `heartcode-embed`.
- Make the recorded placement true: name the SFW canary container after the card it occupies (`pea-sfw-model-canary-gpu6`), and update `configs/gpu-topology.json` so slot `gpu-5` lists `gpu-server-5` + `embedding-server-5`. Commit the canary compose/script parameterisation that PEA already runs uncommitted.
- Correct the stale compose and models.yaml comments that claim GPU 5 hosts a canary and that NSFW runs two replicas.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `gpu-rebalance`: NSFW chat runs at least two routed replicas (GPU 4 and GPU 5); the recorded GPU allocation MUST match what is running.

## Impact

- `gpu-server/docker-compose.yml` (service `gpu-server-5` restored with UUID pin and the 8 GiB memcg limit GPU 4 needed), `gpu-server/models.yaml` (+ regenerated `litellm/config.yaml`, `models.generated.env`), `gpu-server/configs/gpu-topology.json`, `docker-compose.model-canaries.yml`, `scripts/model-canary-operations.sh`, PEA `.env` (`SFW_CANARY_CONTAINER`).
- Deploy: PEA `compose up -d gpu-server-5`; Prod LiteLLM restart to pick up the new deployments; canary container recreated once under its new name (brief canary downtime, no production impact).
- Host RAM on PEA rises by up to 8 GiB worst case (memcg limit); 14 GiB is currently available.

## Non-goals

- No change to admission, cooldown or retry behaviour (see `queue-busy-chat-backends`).
- No restoration of GPU 6 while the SFW canary slot is in use; ending the canary is a separate decision.
- No change to the GPU 5 quarantine policy for >7.6 GiB occupants; this change only places a workload that stays under it.
