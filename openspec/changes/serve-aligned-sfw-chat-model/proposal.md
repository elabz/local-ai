# Serve an Aligned Model on the SFW Chat Route

> **Priority (recorded 2026-09-18 by `project-health-improvements`):** this is
> the top-priority open change. It became access-control critical when HeartCode
> dropped its per-message content filter on 2026-08-29, and it ranks ahead of
> `scale-chat-concurrency` and all other canary or throughput work.

## Why

HeartCode removed per-message content filtering
(`move-content-gating-to-model-layer`, 2026-08-29). Access to adult content is
now governed by age verification plus **the served model's own refusal
behaviour**. That promotes this repo's choice of SFW-route occupant from a
quality decision to a load-bearing access control: whether an unverified user
can obtain adult content is decided here, by which GGUF the `heartcode-chat-sfw`
pool loads.

The pool does not currently hold that boundary. Measured against the live
service on 2026-08-29 under production conditions — the deployed immersion
prompt, an in-character persona, the unauthorized tone contract, and the
production sampler — Stheno v3.4 refused **0 of 3** explicit requests: one trial
produced explicit content outright and two deflected on pacing rather than
declining. The gate is open, and HeartCode no longer has a filtering layer
behind it.

A bare-prompt probe would have missed this. Stheno refuses the same request
asked cold; the immersion prompt's "never break immersion with meta-commentary,
disclaimers, or AI-like behavior" instruction overrides its alignment in role.
Any candidate promoted here must be measured the way production actually calls
it.

## What Changes

- **Load an aligned model in the `heartcode-chat-sfw` pool** — the three
  replicas `pea-gpu-1/2/3` (ports 8080–8082) — replacing
  `Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf`.
- **Point the three `heartcode-chat-sfw` LiteLLM entries at the new weight**, by
  targeted in-place edit on `.152`, never by shipping this repo's
  `litellm/config.yaml` wholesale.
- **Gate promotion on an in-role refusal measurement** taken with HeartCode's
  `scripts/probe_model_refusal.py --profile sfw`, plus a throughput measurement
  taken warm and cold separately, both recorded in the HeartCode repository's
  model canary log under its docs directory, before the pool is switched.
- **Keep the NSFW pool unchanged.** Its occupant must continue not to refuse for
  age-verified users; that was re-measured 0/3 refusals on 2026-08-29 and is
  correct.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `gpu-inference-availability`: the SFW pool acquires a correctness property
  beyond being reachable — the weight it serves must decline explicit content
  under the caller's production system prompt, verified before promotion and
  re-verified whenever the occupant changes.

## Impact

- **Model selection is not yet made and is the operator's call.** The two
  candidates trade off against each other and neither is currently promotable:
  - `gemma-3-12b-it-Q4_K_M` (on disk) refuses **3/3** in role, re-confirmed
    2026-08-29 — and refuses *in character*, as the persona's own boundary
    rather than as an AI. But it measures 13.3 t/s warm and **9.4 t/s cold** on
    a P104-100, below the 12 t/s floor HeartCode's `model-reasoning` spec sets.
  - `Meta-Llama-3.1-8B-Instruct` (~5.4 GB at Q5_K_M) is the architectural
    drop-in — Stheno is a finetune of it, so it inherits the same layer count
    and chat template and should hold ~23 t/s in the existing slot config, with
    alignment intact because the RP finetune is what removed it. **It is not on
    Pea's disk** (confirmed 2026-08-29) and has never been measured in role.
- **GPU layout**: unchanged for an 8B swap. A 12B occupant needs its VRAM
  re-checked against the 8 GB cards — Gemma-3-12B measured 6,607 MiB at
  `--ctx-size 4096`, which fits, but leaves less headroom than the 8B it
  replaces.
- **`gpu-server/.env`**: `GPU_{1,2,3}_MODEL_PATH` / `_MODEL_NAME` change; the
  compose file itself needs no edit since the paths are already parameterized.
- **Chat template**: an 8B Llama drop-in inherits Stheno's template unchanged. A
  Gemma occupant needs its template pinned explicitly in `models.yaml` — a
  stripped GGUF template silently disables llama.cpp's flags.
- **Blocks two HeartCode changes.** `move-content-gating-to-model-layer` cannot
  archive until this lands, and `screen-characters-at-publication` depends on it
  because its rationale for unscreened private import is that an unverified
  user's conversations route to a model that declines.
