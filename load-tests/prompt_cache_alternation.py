#!/usr/bin/env python3
"""Returning-conversation reuse on one worker at a given prompt size (serve-prompt-cache-reuse §4).

K conversations take turns on one chat worker, so each return finds its prompt
evicted from the single slot. Whether it is restored from llama.cpp's host
prompt cache (`--cache-ram`) or evaluated again shows in the response's
`timings`:
- `cache_n` is the tokens restored;
- `prompt_n` is the tokens evaluated.

Run it at K = 1..4 to see how many conversations of this size the current
`CACHE_RAM` keeps. It talks to the worker's wrapper directly, bypassing
LiteLLM, and records numbers only, never text.

    python3 prompt_cache_alternation.py --worker http://192.168.70.144:8080 \\
        --prompt-tokens 7400 --conversations 1 2 3 4 --rounds 3 \\
        --output results/alternation-sfw-7400.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time

import httpx

WORDS = (
    "harbour lantern tide ferry dock rope sail gull storm fog captain river market bread salt "
    "letter promise winter bridge tower orchard well lamp bell road inn traveller map compass"
).split()


def prose(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words))


def ask(client: httpx.Client, messages: list) -> dict:
    start = time.time()
    response = client.post("/v1/chat/completions", json={
        "model": "x", "messages": messages, "max_tokens": 1, "temperature": 0})
    response.raise_for_status()
    timings = response.json().get("timings") or {}
    return {"cache_n": timings.get("cache_n"), "prompt_n": timings.get("prompt_n"),
            "prompt_ms": timings.get("prompt_ms"), "wall_s": round(time.time() - start, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--prompt-tokens", type=int, default=7400)
    parser.add_argument("--conversations", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    words = int(args.prompt_tokens * 0.75)  # ~1.33 tokens per word for this vocabulary
    runs = []
    with httpx.Client(base_url=args.worker, timeout=300) as client:
        for k in args.conversations:
            rng = random.Random(f"alternation-{k}-{time.time()}")
            convs = [[{"role": "system", "content": prose(rng, 40)},
                      {"role": "user", "content": prose(rng, words)}] for _ in range(k)]
            for conv in convs:  # first visit: cold
                ask(client, conv)
            returns = []
            for round_ in range(args.rounds):
                for i, conv in enumerate(convs):
                    # The next turn: the same prompt with a short exchange appended.
                    conv += [{"role": "assistant", "content": prose(rng, 20)},
                             {"role": "user", "content": prose(rng, 15)}]
                    result = ask(client, conv)
                    result.update({"round": round_, "conversation": i})
                    returns.append(result)
                    print(json.dumps({"k": k, **result}), flush=True)
            restored = [r for r in returns if (r["cache_n"] or 0) > args.prompt_tokens // 2]
            runs.append({
                "conversations": k,
                "returns": returns,
                "restored": f"{len(restored)}/{len(returns)}",
                "median_wall_s": statistics.median(r["wall_s"] for r in returns),
            })
    summary = [{k: v for k, v in run.items() if k != "returns"} for run in runs]
    with open(args.output, "w") as fh:
        json.dump({"change": "serve-prompt-cache-reuse §4", "settings": vars(args), "summary": summary,
                   "runs": runs}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
