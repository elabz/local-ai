# NSFW canary wrapper verification — 2026-08-26

The isolated Huihui Qwen3 NSFW canary was changed from a direct
`llama-server` entrypoint to the repository GPU wrapper. The external canary
port remains `18086`; FastAPI listens on container port `8080` and supervises
the pinned llama.cpp child on loopback port `8081`. No public model alias was
changed.

Live Pea verification after the isolated canary was recreated:

- wrapper health reported `ready` and the llama.cpp child reported `ok`;
- the container was healthy with zero restarts;
- the process tree contained `python3 server.py` as parent and the pinned
  `llama-server` build `b10566-bb4caa754` as child;
- the child loaded the selected Q5_K_M artifact at 16K context on the assigned
  GPU with Q8 KV cache;
- a harmless chat request passed `top_k`, `min_p`, `repeat_penalty`, and DRY
  fields through the wrapper and returned the expected marker; measured decode
  throughput for this small probe was approximately 21.9 tokens/second;
- the retained GPU 4 NSFW control and surviving DINO replica remained healthy.

This verifies wrapper topology and sampler passthrough only. It does not
complete the fixed private NSFW quality/safety suite or qualify the candidate
for promotion. The existing wrapper forwards final answer content during
streaming but does not preserve a separate `reasoning_content` delta; that
compatibility limitation remains in scope for the full API probe.

## Canary-only anti-repetition defaults

After word-for-word repetition remained visible through the wrapper, the
supervised llama.cpp child was given canary-only defaults that do not depend on
LiteLLM forwarding extension fields:

- `top_k=20`, `min_p=0`;
- `repeat_penalty=1.1`, `repeat_last_n=256`;
- `presence_penalty=0.15`;
- DRY multiplier/base/allowed-length/lookback `0.8/1.75/2/512`;
- XTC remained disabled and the RNG seed remained random.

The live child `/props` response reported each intended value. Following the
restart, the wrapper and child were healthy with zero restarts. Two harmless
same-prompt prose responses had different content hashes. A separate 164-word
synthetic sample contained zero repeated normalized four-word phrases across
161 four-grams. These are mechanical checks only; the private prompt suite and
the originally failing conversation still determine whether task 4.4 passes.

## Busy-slot failure and queue correction

A caller-visible generation failure was correlated without inspecting prompt
content. At `2026-08-27T02:02:26Z`, the HeartCode/LiteLLM host received two
wrapper `503` responses while a synthetic verification request occupied the
canary's sole inference slot. Wrapper metrics recorded two admission rejections
and a `capacity_exhausted` transition. The container remained healthy with zero
restarts, no OOM, and successful llama.cpp completion of the active request.

The canary wrapper was changed to wait up to 30 seconds for its single slot
instead of rejecting immediately. Its health endpoint now reports healthy while
a live request is merely busy; the watchdog continues to classify and handle a
genuinely stuck request separately.

A live overlapping-request probe verified the correction: busy health returned
HTTP 200, the active request returned HTTP 200 in approximately 12.6 seconds,
and the overlapping request queued and returned HTTP 200 in approximately 14.8
seconds. Post-probe metrics showed no admission rejection, zero in-flight work,
zero restarts, and no OOM. The retained GPU 4 control and surviving DINO replica
remained healthy.
