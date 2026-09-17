# 2026 Gemma 4 NSFW/RP canary comparison — 2026-08-29

## Outcome

`rpDungeon/Gemma-4-E4B-Luchador` Q5_K_M is the only admitted 2026
challenger that passed the current mechanical direct-response, throughput,
allowed-adult refusal, and prohibited-content gates. It is the recommended
first private model to try, but it is not approved for production promotion
until blinded human prose review is completed. Lumimaid remains the production
control.

The fixed suite stores only aggregate flags, lengths, and SHA-256 response
hashes. It does not store prompts or generated prose in this repository.

## Candidate comparison

| Candidate | Release | Pea context / p10 decode | Direct response and compatibility | Fixed quality/safety result | Decision |
|---|---:|---|---|---|---|
| Luchador Q5_K_M | 2026-05-24 | 4K: 20.197 t/s; 8K: 18.938 t/s; 16K: 17.590 t/s | Reasoning off, no visible thought markers, retrieval and native JSON pass; second tool-result turn is empty | 11 responses, no blanks, no allowed-adult refusal, 2/2 prohibited refusals | Provisional winner; private human RP/prose review next |
| Gemma4 12B Balanced Q4_K_M | 2026-06-22 | 4K: 13.255 t/s; 7,389/8,192 MiB VRAM during idle-loaded probe | Multi-turn tools pass, but direct response, retrieval, and native JSON fail; `<|channel>thought` is emitted into normal content with reasoning disabled | Visible thought markers in 11/11 responses and 0/2 prohibited refusals | Rejected for the requested non-thinking mode and safety gate |
| Gemma 4 E4B Aggressive Q6_K_P | 2026-04-02 | 4K: 19.952 t/s | Reasoning off, no visible thought markers, retrieval and native JSON pass; second tool-result turn is empty | No allowed-adult refusal, but 0/2 prohibited refusals | Rejected for HeartCode; retain only as an explicitly unsafe refusal-free lab control |
| Lumimaid v0.2 8B Q5_K_M imatrix | 2024-07-28 | Existing production control | Existing production API | 11 responses, no blanks or reasoning markers, no allowed-adult refusal, 2/2 prohibited refusals | Remains production control pending human comparison |

All throughput rows use ten requests, Q8 KV cache, one inference slot, the
pinned Pascal-compatible llama.cpp build 10566 (`bb4caa754`), and the physical
GPU 6 UUID recorded in each identity file. Means did not substitute for the
12 t/s p10 gate.

## Runtime findings

- The wrapper now forwards native JSON-schema and tool fields, including the
  assistant tool call and following tool-result message.
- Explicit zero sampler values are preserved. Previously `temperature=0` was
  incorrectly replaced by the wrapper default through Python truthiness.
- The recorded context/throughput matrix predates that sampler fix and therefore
  used the wrapper's configured default temperature. The p10 measurements remain
  valid decode-speed evidence, but they are not claimed as deterministic-output
  runs. Final compatibility and quality/safety probes were rerun after the fix.
- The compatibility harness detects reasoning both in
  `message.reasoning_content` and as visible thought/control tokens in normal
  content.
- Luchador and Aggressive share a Gemma 4 template limitation on this pinned
  build: they emit the first forced tool call, but answer the following tool
  result with empty content. This does not block ordinary character chat, but
  it blocks workflows requiring native multi-turn tools.
- The 12B model took about 82 seconds to become ready and left roughly 803 MiB
  VRAM free at 4K. No larger context was attempted after its direct-response
  and prohibited-content gates failed.

## Provenance and artifacts

Exact repositories, immutable revisions, filenames, quantizations, SHA-256
digests, license labels, runtime build, and GPU identity are stored in the
adjacent identity JSON files. All three 2026 artifacts matched their published
byte sizes and digests before loading. No multimodal projector or speculative
MTP head was downloaded or used.

The superseded Huihui Qwen3 canary weight had zero active container references
and was removed to make room for the three approved 2026 artifacts. It is
recoverable from its recorded upstream repository.

## Routing and rollback

No public SFW or NSFW alias was modified. Repository LiteLLM additions are
isolated canary-only model IDs sharing port 18086; only the artifact explicitly
loaded by an operator can answer there.

At terminal rollback, the isolated GPU 6 canary container was removed. GPU 4
and GPU 6 Lumimaid plus both DINO replicas were running, healthy, at zero
restarts, and not OOM-killed. A permanent Luchador promotion would require a
separate change and a co-location test for the GPU 6 DINO replica.

## Remaining release work

Run blinded human scoring of Luchador versus Lumimaid for character fidelity,
naturalness, repetition, prose quality, and tone. Promotion remains blocked
until those scores pass and the product owner decides whether native
multi-turn tool compatibility is required for the NSFW chat route.
