# Tasks — serve-aligned-sfw-chat-model

Cross-repo companion to HeartCode's `move-content-gating-to-model-layer`
section 1. The coordination checkboxes are 5.1–5.3; HeartCode's 1.1–1.5 are the
other side of the same pair.

## 0. Decision

- [ ] 0.1 **Operator selects the SFW candidate.** Neither option is promotable on present evidence: `gemma-3-12b-it-Q4_K_M` refuses 3/3 in role (2026-08-29) but runs 9.4 t/s cold, below the 12 t/s floor; `Meta-Llama-3.1-8B-Instruct` should hold ~23 t/s as an architectural drop-in for Stheno but is not on Pea's disk and has never been measured. See the Open Questions table in design.md
- [ ] 0.2 If the choice is Llama-3.1-8B-Instruct, fetch the Q5_K_M GGUF into Pea's private model storage and verify revision and digest without printing private paths

## 1. Measure the candidate before promoting it

- [ ] 1.1 Load the candidate on the **SFW canary slot** (`pea-sfw-model-canary-gpu5`, port 18085), not the production pool
- [ ] 1.2 Configure the canary slot exactly like a production worker — including `--cache-reuse`, whose omission previously made a canary's TTFT unrepresentative — or the measurement is not comparable
- [ ] 1.3 For a Gemma or Qwen3 candidate, pin the chat template explicitly in `models.yaml`; a stripped GGUF template silently disables llama.cpp's flags
- [ ] 1.4 Grant the candidate id on the HeartCode backend's LiteLLM virtual key (`/key/update` with the master key) so the probe and the chat-quality corpus can reach it
- [ ] 1.5 Measure in-role refusal: `docker exec heartcode-backend-dev python scripts/probe_model_refusal.py --model <candidate> --profile sfw --trials 3`. **Read every transcript** — the printed verdict is a keyword sort and has already mis-scored a correct refusal. Reject the candidate if it does not decline
- [ ] 1.6 Measure throughput cold and warm as separate figures, at a short prompt and at a production-sized ~2,150-token prompt. Reject if the cold figure is below the floor and the operator does not explicitly accept it
- [ ] 1.7 Record both measurements in the HeartCode repository's model canary log, under its docs directory, before proceeding
- [ ] 1.8 Run HeartCode's chat-quality corpus against the candidate through a per-character model pin, so quality is measured before the route moves — an over-refusing occupant degrades ordinary romantic roleplay, which is the false-positive failure this architecture exists to avoid

## 2. Promote into the SFW pool

- [ ] 2.1 Confirm VRAM headroom under sustained three-replica load, not a single probe — a 12B occupant leaves a thinner margin on the 8 GB cards than the 8B it replaces
- [ ] 2.2 Update `GPU_{1,2,3}_MODEL_PATH` and `GPU_{1,2,3}_MODEL_NAME` in `gpu-server/.env`; the compose file needs no edit, the paths are already parameterized
- [ ] 2.3 Recreate `pea-gpu-1`, `pea-gpu-2`, `pea-gpu-3`. Update `pea-gpu-controller.service`'s slot inventory rather than fighting its 60s re-up poll
- [ ] 2.4 Keep the Stheno GGUF on disk for rollback
- [ ] 2.5 Edit the three `heartcode-chat-sfw` entries' `model:` field on `.152` **in place**; never ship this repo's `litellm/config.yaml` wholesale — the live file carries canary, STT/TTS, and tuning entries a copy would delete
- [ ] 2.6 `restart` LiteLLM; `up -d` does not reload a bind-mounted config
- [ ] 2.7 Verify all three replicas serve the new weight and that no route still points at a dead port — a route with no listener returns 500 then cools down to 429 for ~90s, which the application surfaces as "we are busy"

## 3. Verify on the production route

- [ ] 3.1 Re-measure in-role refusal against `heartcode-chat-sfw` itself and record it in the canary log's refusal matrix
- [ ] 3.2 Confirm the NSFW pool still does not refuse for an authorized caller: `--model heartcode-chat-nsfw --profile nsfw` (0/3 refusals on 2026-08-29; must stay that way)
- [ ] 3.3 Confirm end-to-end through the application, not only through the proxy
- [ ] 3.4 Watch for OOMs, restarts, and host RAM/swap across the first sustained load window

## 4. Rollback readiness

- [ ] 4.1 Record the exact commands to restore the previous weight and proxy entries
- [ ] 4.2 Note in the rollback record that reverting reopens the access gate, so it is a step toward a different candidate rather than a resting state

## 5. Cross-repo coordination

- [ ] 5.1 HeartCode `move-content-gating-to-model-layer` task 1.1 (model selected) ← pairs with 0.1 here
- [ ] 5.2 HeartCode task 1.3 (chat-quality corpus run) ← pairs with 1.8 here
- [ ] 5.3 HeartCode task 1.4 (in-role refusal re-verified after the swap) ← pairs with 3.1 here
- [ ] 5.4 Notify HeartCode when this lands: it unblocks the archive of `move-content-gating-to-model-layer` and the start of `screen-characters-at-publication`, whose rationale for unscreened private import depends on the SFW route declining
