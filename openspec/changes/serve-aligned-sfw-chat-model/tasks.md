# Tasks — serve-aligned-sfw-chat-model

Cross-repo companion to HeartCode's `move-content-gating-to-model-layer`
section 1. The coordination checkboxes are 5.1–5.3; HeartCode's 1.1–1.5 are the
other side of the same pair.

## 0. Decision

- [x] 0.1 **Operator selects the SFW candidate.** — 2026-10-10: operator chose **Gemma 4 E4B-it** (April 2026) for trial over Llama-3.1-8B-Instruct; gemma-3-12b was below the throughput floor and its GGUF has since been removed from Pea (re-downloadable). Original options: `gemma-3-12b-it-Q4_K_M` refuses 3/3 in role but runs 9.4 t/s cold; `Meta-Llama-3.1-8B-Instruct` unmeasured
- [x] 0.2 Fetch the candidate into Pea's model storage and verify revision and digest — 2026-10-10: Google's QAT Q4_0 `gemma-4-E4B_q4_0-it.gguf`, rev `4b4a2c1d`, sha256 verified against the Hub record, stored as `gemma-4-E4B-it-qat-q4_0.gguf`

## 1. Measure the candidate before promoting it

- [x] 1.1 Load the candidate on the SFW canary slot — 2026-10-10: on GPU 3's card (`pea-sfw-model-canary-gpu3`, :18085), not GPU 5 (garbles above ~6.6 GiB) or GPU 6 (serves NSFW). GPU 3's chat replica and DINO embedder displaced and unrouted (min_replicas lowered, dated); controller inventory carries a schema-2 canary record (owner ran `~/lend-gpu3-to-canary.sh`; `--restore` reverses)
- [x] 1.2 Configure the canary slot exactly like a production worker — 16,384 ctx, batch 128/64, Q8 KV, `--cache-reuse 256`, plus `--cache-ram 1024` (now in the canary compose) and `--reasoning off` (llama.cpp otherwise enables Gemma 4 thinking and replies come back empty)
- [x] 1.3 Chat template — not pinned: the GGUF carries Google's canonical Gemma 4 template (2026-07-09), whose `enable_thinking` defaults false; the server flag above handles llama.cpp's override
- [x] 1.4 Grant the candidate id on the HeartCode backend's LiteLLM virtual key — `heartcode-chat-gemma-4-e4b-canary` appended to `heartcode-backend`'s grant; route in `extra_model_list`
- [x] 1.5 Measure in-role refusal — 2026-10-10: single turn 0/5 explicit, but under sustained pressure two conversations gave way by turn 7–8 with HeartCode's old tone contract. HeartCode firmed the SFW contract; then `--trials 5 --pressure 7`: Gemma 0/5 narrated sex across 40 replies, Stheno 3/5 (2/5 fully explicit). Transcripts read in full; see HeartCode docs/model-canary-log.md
- [x] 1.6 Measure throughput cold and warm — short 25.3 t/s (TTFT 0.11 s); 1,538-token cold TTFT 3.23 s at 24.4 t/s; warm 0.10 s; next turn 0.64 s at 24.6 t/s. Above Stheno's 23.5 t/s
- [x] 1.7 Record both measurements in HeartCode's docs/model-canary-log.md — 2026-10-10
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
