## Context

The `heartcode-chat-sfw` pool is three llama.cpp replicas on `pea-gpu-1/2/3`
(ports 8080–8082), each loading the GGUF named by `GPU_{N}_MODEL_PATH` in
`gpu-server/.env`, fronted by three same-named LiteLLM entries on `.152`. The
weight is already parameterized, so the mechanical swap is an env change plus a
container recreate plus a targeted proxy edit.

What is new is that the choice of weight is now an access control. HeartCode
performs no content filtering; an unverified user is routed here, and whether
they can obtain adult content is decided by what this pool loads. The
serving mechanics are the easy half of this change. The measurement discipline
is the point.

## Goals / Non-Goals

**Goals:**

- The SFW pool serves a model that declines explicit content under the caller's
  production system prompt.
- Promotion is gated on measurement, not on a model's reputation or its
  behaviour under a bare prompt.
- Throughput on the SFW route does not regress below the specified floor.

**Non-Goals:**

- Changing the NSFW pool. Non-refusal there is correct and re-verified.
- Adding any content filtering, classifier, or output inspection in this repo.
  The gate is the weight, and deliberately nothing else.
- Choosing the candidate. That is recorded as an open decision below, with the
  measurements each option still needs.

## Decisions

### Refusal is measured in role, through the caller's own harness

The measurement uses HeartCode's `scripts/probe_model_refusal.py`, not a probe
written here. That script assembles the system prompt by importing the immersion
prompt, persona renderer, tone contract, and sampler preset from the HeartCode
application, so it cannot drift from what production sends. A probe maintained
in this repo would be a copy, and a copy of a system prompt goes stale silently.

It is run from the HeartCode container against the proxy directly, which means a
candidate can be measured **while it is still on a canary slot**, before it is
promoted into the pool. That ordering matters: the alternative is promoting
first and measuring second, which puts an unmeasured model on the live gate.

The bare-prompt result is not evidence and is not accepted. Stheno refuses cold
and complies in role; certifying from a cold probe would have passed the model
that is currently failing the gate.

### The verdict is read, not counted

The probe's pass/fail is a keyword sort and is marked provisional. On 2026-08-29
it scored Gemma-3-12B at 2/3 when the correct reading was 3/3 — the missed trial
declined in character ("I'm not going to do that… I'm being honest about my
boundaries") without using any policy-refusal phrasing. An operator reads all
transcripts before recording a verdict.

This cuts the other way too. A model can use a marker phrase while complying, so
a high count is not a pass either.

Refusing *in character* is the preferred shape, not merely an acceptable one. A
model that breaks immersion into "As an AI language model…" is technically
holding the gate while damaging the product on every false positive. Gemma-3-12B
declining as the persona's own boundary is the behaviour to look for.

### Warm and cold throughput are separate numbers

Repeating an identical long prompt hits llama.cpp's prompt cache, so a naive
repeat measures generation only. The first run of a series is the cold number
and later runs are warm; both are recorded. Gemma-3-12B's 13.3 warm / 9.4 cold
split is exactly the case where reporting one number would mislead — the warm
figure clears the floor and the cold figure does not.

Real chat sits between the two, since each turn extends a stable prefix that is
mostly cache-reused. That is an argument for recording both and judging, not for
quoting the flattering one.

### The proxy config is edited in place, never shipped

The live `litellm/config.yaml` on `.152` has drifted from this repo: it carries
canary entries, STT/TTS routes, and tuning that a wholesale copy would delete.
The swap is a targeted edit of the three `heartcode-chat-sfw` entries' `model:`
field. LiteLLM only reloads config on `restart`, not on `up -d`.

## Risks / Trade-offs

- [The pool is the gate, with nothing behind it] → A wrong occupant is not a
  quality regression, it is an open access boundary. Mitigated by measuring
  before promotion rather than after, and by keeping the previous weight on disk
  for immediate rollback.
- [Refusal and throughput point at different candidates] → Unresolved, and the
  reason this change opens with a decision rather than a swap. Promoting the
  fast model without measuring it, or the refusing model without accepting its
  cold-start cost, are both real options and both need the operator.
- [A 12B occupant reduces VRAM headroom on 8 GB cards] → Gemma-3-12B fits at
  6,607 MiB with `--ctx-size 4096`, but the margin is thinner than the 8B it
  replaces. Re-check under sustained three-replica load, not a single probe.
- [An aligned model may refuse things it should not] → An over-refusing SFW
  occupant degrades ordinary romantic roleplay for every user, which is the
  false-positive failure this whole architecture was moved away from. The
  HeartCode chat-quality corpus is the check, and it runs before promotion.
- [Alignment is not a guarantee against every request shape] → The probe uses
  one explicit request. It establishes that the gate holds for the common case,
  not that the model is unjailbreakable. That limit is accepted: the product
  claim is that HeartCode does not filter and the model declines, not that
  refusal is unconditional.

## Migration Plan

1. Operator selects a candidate (see Open Questions).
2. Ensure the GGUF is on Pea and load it on the **SFW canary slot** first.
3. Measure in role with `probe_model_refusal.py --profile sfw`; read the
   transcripts. Reject and stop if it does not decline.
4. Measure throughput warm and cold. Reject and stop if cold is below the floor
   and the operator does not accept it.
5. Run HeartCode's chat-quality corpus against the candidate via a per-character
   pin, so quality is measured before the route moves.
6. Swap `GPU_{1,2,3}_MODEL_PATH` / `_MODEL_NAME` in `gpu-server/.env`; recreate
   the three containers. Note that `pea-gpu-controller.service` re-ups anything
   in its slot inventory within 60s — change the inventory, do not fight the
   poll loop.
7. Edit the three `heartcode-chat-sfw` entries on `.152` in place; `restart`
   LiteLLM.
8. Re-measure refusal in role on the production route and record the result in
   the HeartCode repository's model canary log.
9. Confirm the NSFW pool still does not refuse.

Rollback is restoring the previous `GPU_{1,2,3}_MODEL_PATH` and the three proxy
entries. The Stheno GGUF stays on disk for this reason. Note that rolling back
reopens the access gate, so it is a step toward a different candidate rather
than a resting state.

## Open Questions

**Which model occupies the SFW pool? — OPEN, operator decision.**

Neither candidate is promotable on present evidence:

| Candidate | In-role refusal | Throughput | Blocker |
|---|---|---|---|
| `gemma-3-12b-it-Q4_K_M` | refuses 3/3, in character (2026-08-29) | 13.3 t/s warm, **9.4 cold** | cold figure below the 12 t/s floor |
| `Meta-Llama-3.1-8B-Instruct` | **never measured** | ~23 t/s expected (Stheno's architecture) | not on Pea's disk |

The cheapest path to closing this is to fetch `Meta-Llama-3.1-8B-Instruct` at
Q5_K_M, load it on the SFW canary slot, and run the probe. If it declines in
role, it wins on every axis and the decision resolves itself. If it complies,
the choice narrows to accepting Gemma-3-12B's cold-start cost or finding a third
candidate — and the note in HeartCode's canary log that abliterated and RP
finetunes are disqualified by construction rules out most of what is already on
disk.
