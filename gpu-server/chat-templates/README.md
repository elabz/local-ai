# Chat templates

Pinned Jinja chat templates, selected per model instead of trusting whatever
template a GGUF happens to embed.

| file | format | delimiters | use for |
|---|---|---|---|
| `llama3.jinja` | Llama 3.x Instruct | `<\|start_header_id\|>` | Stheno, Lumimaid, any Llama-3.1/3.2/3.3 finetune |
| `gemma.jinja` | Gemma instruct | `<start_of_turn>` | Gemma 2 / Gemma 3 instruct models |
| `qwen3.jinja` | Qwen3 ChatML | `<\|im_start\|>` | Qwen3 (incl. thinking mode via `enable_thinking`) |

## Why pin at all

Published GGUFs have shipped broken templates — missing `<think>` handling,
wrong role delimiters, and KV-cache-invalidating whitespace are all documented
upstream. Pinning makes the prompt format an explicit, reviewable, diffable
input rather than a property of whichever quantisation you happened to download.

## Selecting one

In `gpu-server/models.yaml`, on any `kind: chat` model:

```yaml
- api_name: heartcode-chat-sfw
  kind: chat
  chat_template: llama3      # omit entirely to use the GGUF's own template
```

`render-config.py` validates the name against the files in this directory and
fails the build with the list of valid names if it does not match. It then emits
`GPU_<n>_CHAT_TEMPLATE` into `models.generated.env`; compose passes that as
`CHAT_TEMPLATE_FILE`, and the wrapper appends `--chat-template-file` (implying
`--jinja`). Omitting the key emits an empty value, which is exactly the
historical behaviour — so this is opt-in per model.

The `qwen3-canary` service bypasses the wrapper (it runs `llama-server`
directly), so it names `--chat-template-file` in its compose `command:`.

## Provenance

- `qwen3.jinja` — extracted from the deployed `Qwen3-8B-Q4_K_M.gguf` via
  `llama-server`'s `/props`, so it is exactly what that model expects.
- `llama3.jinja`, `gemma.jinja` — llama.cpp's canonical
  `models/templates/` at tag `v0.2.0`.

## Verifying what a server actually loaded

```bash
curl -s http://<host>:<port>/props | python3 -c \
  "import sys,json,hashlib; t=json.load(sys.stdin)['chat_template']; \
   print(len(t), hashlib.sha1(t.encode()).hexdigest()[:12])"
```

Compare against the file here. Matching sha1 means the pin took effect.
