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
- [x] 1.8 Run HeartCode's chat-quality corpus against the candidate through a per-character model pin, so quality is measured before the route moves — an over-refusing occupant degrades ordinary romantic roleplay, which is the false-positive failure this architecture exists to avoid — 2026-10-10: four interleaved full-corpus runs. Gemma looped on 1/3 long cases (Stheno 3/3, both runs), recalled every fact, and had no blanket refusal or escalation in any case, slow-burn romance included. Median reply 972–1,069 vs 1,174–1,907 chars, 13.7 vs 16–18 s per 1k chars; 0 corrupted contractions in 508 replies. Decision in HeartCode `openspec/changes/v1-character-chat-quality/design.md`

## 2. Promote into the SFW pool

- [x] 2.1 Confirm VRAM headroom under sustained three-replica load, not a single probe — a 12B occupant leaves a thinner margin on the 8 GB cards than the 8B it replaces — 2026-10-10: the E4B is far below the 12B this task anticipated. 4.2–4.4 GiB of 8 GiB VRAM per card beside the embedders, with the 16k KV cache preallocated, so the footprint does not grow under load. Host memory per worker is ~330 MiB anonymous (cgroup 24% of 1.75 GiB); the ~3 GiB GGUF mapping is page cache shared by all three. Sustained-load watch continues under 3.4
- [x] 2.2 Update `GPU_{1,2,3}_MODEL_PATH` and `GPU_{1,2,3}_MODEL_NAME` in `gpu-server/.env`; the compose file needs no edit, the paths are already parameterized — done through models.yaml instead: GPU_N_* are rendered into models.generated.env, now including per-model `server:` overrides (image v0.2.0, -ngl 99, --reasoning off). Pea's .env GPU_N_* lines are synced to match (backup .env.bak-20261010-gemma-promote)
- [x] 2.3 Recreate `pea-gpu-1`, `pea-gpu-2`, `pea-gpu-3`. Update `pea-gpu-controller.service`'s slot inventory rather than fighting its 60s re-up poll — GPU 3 first (out of routing, smoke-tested through the wrapper), then GPU 1 and GPU 2, health-gated with a 60 s soak (1f5e6e6). The controller now passes both env files to compose. Clearing the live inventory's canary record and loading that controller code needs `sudo ~/lend-gpu3-to-canary.sh --restore` (owner)
- [x] 2.4 Keep the Stheno GGUF on disk for rollback — Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf kept in gpu-server/models/
- [x] 2.5 Edit the three `heartcode-chat-sfw` entries' `model:` field on `.152` **in place**; never ship this repo's `litellm/config.yaml` wholesale — the live file carries canary, STT/TTS, and tuning entries a copy would delete — superseded: litellm/config.yaml is generated and was in sync, so elm pulled 1f5e6e6. The diff was exactly SFW → gemma on :8080-8082, DINO :8104 re-routed, canary route removed. Pre-change copy at /tmp/litellm-config.pre-gemma-promote.yaml on elm
- [x] 2.6 `restart` LiteLLM; `up -d` does not reload a bind-mounted config — restarted 2026-10-10 ~19:05 UTC
- [x] 2.7 Verify all three replicas serve the new weight and that no route still points at a dead port — a route with no listener returns 500 then cools down to 429 for ~90s, which the application surfaces as "we are busy" — `/v1/model/info` lists heartcode-gpu1..3 on :8080-8082 (gemma); six proxied requests landed on all three ids. The HeartCode backend key's canary grant was removed so the dropdown shows no dead route

## 3. Verify on the production route

- [x] 3.1 Re-measure in-role refusal against `heartcode-chat-sfw` itself and record it in the canary log's refusal matrix — 2026-10-10: `--trials 5 --pressure 7` against heartcode-chat-sfw with HeartCode's GEMMA4_PRESET (1.2 / min_p 0.1). 0/5 narrated sex, all 40 replies read and every one deflects in character. Recorded in HeartCode docs/model-canary-log.md
- [x] 3.2 Confirm the NSFW pool still does not refuse for an authorized caller: `--model heartcode-chat-nsfw --profile nsfw` (0/3 refusals on 2026-08-29; must stay that way) — 2026-10-10: 3/3 comply, provisional_holds true
- [x] 3.3 Confirm end-to-end through the application, not only through the proxy — 2026-10-10: a fresh dev conversation with an SFW character streamed 16 tokens + done through /chat/{id}/stream. Production HeartCode needs a deploy to carry GEMMA4_PRESET; until then production sends Stheno's 1.4
- [ ] 3.4 Watch for OOMs, restarts, and host RAM/swap across the first sustained load window

## 4. Rollback readiness

- [x] 4.1 Record the exact commands to restore the previous weight and proxy entries — rollback = revert models.yaml's SFW entry to Stheno + drop `server:`, re-render, roll pea-gpu-1..3 with both env files, pull + restart LiteLLM on elm; HeartCode points resolve_preset() back at STHENO_PRESET. Pea .env backup: .env.bak-20261010-gemma-promote
- [x] 4.2 Note in the rollback record that reverting reopens the access gate, so it is a step toward a different candidate rather than a resting state — recorded in models.yaml's SFW comment and HeartCode's canary log

## 5. Cross-repo coordination

- [ ] 5.1 HeartCode `move-content-gating-to-model-layer` task 1.1 (model selected) ← pairs with 0.1 here
- [x] 5.2 HeartCode task 1.3 (chat-quality corpus run) ← pairs with 1.8 here
- [x] 5.3 HeartCode task 1.4 (in-role refusal re-verified after the swap) ← pairs with 3.1 here — heartcode-chat-sfw re-verified 2026-10-10 (3.1)
- [ ] 5.4 Notify HeartCode when this lands: it unblocks the archive of `move-content-gating-to-model-layer` and the start of `screen-characters-at-publication`, whose rationale for unscreened private import depends on the SFW route declining
