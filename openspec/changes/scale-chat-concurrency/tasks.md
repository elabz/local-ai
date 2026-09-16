## 1. Measurement

- [ ] 1.1 Add a k6 mixed-load scenario reporting aggregate tok/s, p95 TTFT, per-stream decode, VRAM per replica
- [ ] 1.2 Qualify `MAX_CONCURRENT_REQUESTS=2` (8K per slot) on one NSFW replica; record evidence and decision
- [ ] 1.3 Roll the qualified slot count to the fleet via compose env; update admission wait and proxy timeouts

## 2. Priority and affinity

- [ ] 2.1 Enable Redis for the LiteLLM router and set `priority` per key (interactive 0, batch 1); test saturation ordering
- [ ] 2.2 Implement session affinity (custom routing strategy + Redis session map with TTL) and expose cache-hit metrics from llama.cpp slot stats
- [ ] 2.3 Document `X-Session-Id` and shared-prefix-first prompt layout in the client contract

## 3. Capacity model

- [ ] 3.1 Generate and commit the per-group capacity table (slots, throughput, decode, queue-wait by concurrency) in `docs/load-test-findings.md`
- [ ] 3.2 Add a CI reminder (manifest comment or check) that slot/model changes require regenerating the table
