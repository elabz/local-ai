# Gemma and JSON compatibility evidence (2026-08-25)

## Runtime

- Canary image: `local-ai-llama:v0.2.0`, llama.cpp commit `bb4caa754`.
- SFW GPU 5 used the isolated canary port only; the production aliases were not changed.
- Gemma 3 12B Instruct Q4_K_M loaded at 4K, 8K, and 16K. The 16K load was stable but left approximately 243 MiB free on the 8 GiB card. A 24K load failed during CUDA allocation and exited cleanly; no OOM kill or restart was observed. Per the stop rule, 32K was not attempted for this quant.
- Gemma 3 4B Instruct Q8_0 loaded at 16K with approximately 4.35 GiB VRAM in use and no restart.

## Throughput

- Gemma 3 12B Q4_K_M synthetic 16K/long-prompt decode: p10 approximately 13.2 t/s (13.19 t/s in the five-request run), above the 10 t/s SFW floor.
- Gemma 3 4B Q8_0 synthetic 16K/long-prompt decode: p10 approximately 24.9 t/s, above the SFW floor.
- The NSFW Huihui Qwen3 8B abliterated v2 Q5_K_M challenger on GPU 6 measured approximately 23.0 t/s p10 at 16K, above the 12 t/s NSFW floor.

## Structured output

- A short native `json_schema` probe succeeds for Gemma 12B and Gemma 4B. The embedded Gemma Jinja template is correct: user turn, end-of-turn, model turn, and generation marker are all present.
- Long native-schema Gemma 12B requests fail inside llama.cpp grammar handling with an empty grammar stack after a Gemma unused/control token. This is a runtime grammar/control-token compatibility failure, not evidence of a malformed chat template.
- The site-2017 adapter now supports `LOCAL_LLM_STRUCTURED_MODE=prompt`: it embeds the exact extraction schema in the system prompt, omits provider grammar, performs syntax-only extraction/cleanup, and keeps the existing unchanged semantic validation. Native mode remains the default.
- A ten-thread site-2017 prompt-mode smoke run against the Gemma canary completed 10 successful calls and 2 calls rejected by existing semantic validation (`invalid stakes`); no privacy rejections occurred. This is useful evidence that Gemma remains viable, but it is below the 98% validity gate and is not a winner.

## Restoration

After the canary window, the temporary services were removed and the displaced text-embedding, Lumimaid, and DINO containers were started again. The old Qwen canary was then stopped so the shared isolated SFW port cannot silently serve Qwen responses to a queued Gemma ID. Both isolated canary ports are inactive until an explicitly matching model is loaded; no production alias was modified.

## HeartCode test registration

The LiteLLM configuration now exposes these non-default, selector-visible IDs:

- `heartcode-chat-gemma-3-4b-canary` → isolated SFW canary port `18085`
- `heartcode-chat-gemma-3-12b-canary` → isolated SFW canary port `18085`
- `heartcode-chat-huihui-qwen3-nsfw-canary` → isolated NSFW canary port `18086`

They are deliberately not aliases of either production group. The canary operation script must load the corresponding GGUF on the isolated port before a queued HeartCode test is sent; only one SFW candidate can be active on GPU 5 at a time.

The HeartCode inference key was also updated in LiteLLM to include all four canary IDs (the existing Qwen canary plus the three new candidates). Before this update, LiteLLM correctly hid the new IDs from HeartCode despite them being present in `config.yaml`.
