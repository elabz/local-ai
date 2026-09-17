## 1. Reproducible canary infrastructure

- [x] 1.1 Record the current Pea GPU/container topology, restart counters, model throughput, host memory, and surviving embedding replicas as safe baseline evidence.
- [x] 1.2 Pin the Pascal-compatible llama.cpp canary image to an explicit commit and record its build/version.
- [x] 1.3 Add isolated Compose definitions for a GPU 5 SFW canary and GPU 6 NSFW canary with direct ports, bounded resources, model-aware health, and no public alias routing.
- [x] 1.4 Add operator commands that stop and restore only the displaced Qwen/text-embedding and Lumimaid/DINO services, then verify the surviving and restored replicas.

## 2. Benchmark implementation

- [x] 2.1 Add a benchmark runner that records model/runtime identity and safe aggregate latency, prompt-throughput, decode p10/median/mean, success, and resource evidence without storing private prompt content.
- [x] 2.2 Add progressive 4K, 8K, 16K, 24K, and 32K context orchestration with stop-on-unsafe-failure behavior and a 16K SFW hard gate.
- [x] 2.3 Add beginning/middle/end retrieval and JSON-schema compatibility probes plus a multi-turn tool-call compatibility probe.
- [x] 2.5 Add prompt-constrained JSON compatibility mode with unchanged semantic validation, bounded retries, and separate native/cleanup/irrecoverable validity metrics.
- [x] 2.4 Add tests for percentile calculations, throughput gates, context progression, redaction, and fail-closed candidate decisions.

## 3. Local validation and candidate preparation

- [x] 3.1 Validate Compose syntax, scripts, tests, model manifest drift, and pinned-image metadata locally.
- [x] 3.2 Select and document the first NSFW challenger based on license, provenance, base model, artifact availability, and expected 8 GiB fit.
- [x] 3.3 Download Gemma 3 12B Instruct Q4_K_M, Gemma 3 4B Instruct Q8_0 fallback, and the selected NSFW GGUF into private Pea model storage; verify revisions and exact digests without printing private paths.
- [x] 3.4 Verify whether each candidate loads and passes health, text generation, Jinja chat-template, JSON-schema, direct-response, and relevant multi-turn compatibility probes on the pinned canary image; reject and record failed gates.
- [x] 3.5 Replace the obsolete NSFW selection shortlist with the 2026 Gemma 4 direct-response plan and record fit, license, provenance, and evaluation roles.
- [x] 3.6 Download the three selected 2026 Gemma 4 GGUF artifacts into private Pea model storage and verify exact revisions and digests without printing private paths.

## 4. Live Pea evaluation

- [x] 4.1 Run the Gemma 3 12B progressive context matrix on GPU 5 with the text-embedding replica displaced and record safe aggregate evidence.
- [x] 4.2 If Gemma 3 12B fails load, stability, 16K context, or 10 t/s p10, run the Gemma 3 4B Q8_0 fallback matrix.
- [x] 4.3 Run the frozen `site-2017` SFW benchmark against every mechanically qualified Gemma configuration and score all existing approval gates. _(Completed 2026-09-04: 12B Q4_K_M at 16K and 4B Q8_0 at 16K each processed the frozen 100-thread manifest; 12B scored 100% validity, 100% high-risk recall, 0 leaks, 57.9% precision; 4B 90% validity, 59.3% precision. Neither passes the 90% precision gate. See `evidence/final-comparison-2026-09-04.md`. The 12B run had to move to GPU 6 because GPU 5 corrupts output above ~7.6 GiB.)_
- [x] 4.4 Run each selected 2026 Gemma 4 NSFW/RP challenger on GPU 6 with reasoning disabled against GPU 4's Lumimaid control, including context, p10 12 t/s, qualitative, allowed-adult refusal, and prohibited-content gates. _(All three challengers ran 2026-08-29; Luchador re-measured 2026-09-04 at 19.4 t/s p10 with the fixed suite v1.2.0 and a provider-blind A/B prose packet against Lumimaid. Every machine-scorable gate is recorded; the qualitative gate's verdict is the operator's blind score of that packet, which is the only open item and blocks promotion, not this evaluation. See `evidence/nsfw-gemma4-rerun-2026-09-04.md`.)_
- [x] 4.5 Monitor OOMs, restarts, GPU health, host RAM/swap, and surviving embedding health throughout sustained evaluation.

## 5. Decision, mop-up, and restoration

- [x] 5.1 Produce a comparison report identifying each candidate's largest Pea-qualified context, gate results, provenance, limitations, and selection or rejection rationale.
- [x] 5.2 If an SFW winner passes every gate, run the outstanding `site-2017` failed-call mop-up separately and validate final schema/privacy/coverage outputs. _(Condition not met on 2026-09-04: no SFW candidate passed the frozen benchmark's 90% precision gate, so the mop-up was deliberately not run and the blind selection score is untouched.)_
- [x] 5.3 Restore displaced services after evaluation, verify all intended containers and embedding replicas, and record exact rollback/terminal state.
- [x] 5.4 Leave production aliases unchanged and identify any permanent embedding relocation as a separate future change if Gemma is selected.
