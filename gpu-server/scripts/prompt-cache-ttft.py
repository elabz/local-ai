#!/usr/bin/env python3
"""Measure host prompt-cache reuse on one chat worker (bound-llama-host-prompt-cache, design D5).

Each worker has one slot (--parallel 1), so alternating N conversations round-robin
evicts every conversation from the slot before it returns. A returning turn is fast
only if llama-server restores its prefix from the host-RAM prompt cache
(--cache-ram). The script reports llama.cpp's own `timings` for every returning
turn: `cache_n` (prompt tokens reused) and `prompt_ms` (server-side prompt
processing, i.e. TTFT without network), plus client-side wall time.

Talk to the worker directly (e.g. http://192.168.70.144:8082), never through
LiteLLM, which adds ~1.2 s and may pick another replica.

Usage:
  prompt-cache-ttft.py --url http://192.168.70.144:8082 --sessions 2 4 8 --rounds 3 \
      --prompt-tokens 2000 --label cache-ram-8192 --out evidence.json
  prompt-cache-ttft.py --url ... --distinct 30 --prompt-tokens 2000   # fill the cache (RSS plateau)

Pure stdlib so it runs anywhere without a venv.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.request

WORDS = [
    "harbor", "lantern", "orchard", "violet", "granite", "meadow", "copper", "whisper",
    "cedar", "ember", "river", "quartz", "falcon", "willow", "thunder", "saffron",
    "glacier", "marble", "hollow", "tide", "compass", "velvet", "summit", "juniper",
    "canyon", "ivory", "cobalt", "thistle", "beacon", "prairie",
]


def filler(seed: str, tokens: int) -> str:
    """Deterministic, session-unique text of roughly `tokens` tokens (~1.3 tokens/word)."""
    rng = random.Random(seed)
    words = [rng.choice(WORDS) for _ in range(int(tokens / 1.3))]
    lines = [" ".join(words[i:i + 12]) + "." for i in range(0, len(words), 12)]
    return f"Session {seed}. Character notes follow.\n" + "\n".join(lines)


def chat(url: str, messages: list[dict], timeout: float) -> tuple[dict, float]:
    body = json.dumps({"model": "measure", "messages": messages, "max_tokens": 1,
                       "temperature": 0}).encode()
    req = urllib.request.Request(f"{url}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data, time.monotonic() - start


def run_sessions(url: str, n: int, rounds: int, prompt_tokens: int, nonce: str,
                 timeout: float) -> list[dict]:
    convs = [[{"role": "system", "content": filler(f"{nonce}-{n}-{i}", prompt_tokens)}]
             for i in range(n)]
    rows = []
    for rnd in range(rounds):
        for i, conv in enumerate(convs):
            conv.append({"role": "user", "content": f"Turn {rnd}: continue the scene."})
            data, wall = chat(url, conv, timeout)
            conv.append({"role": "assistant",
                         "content": data["choices"][0]["message"].get("content") or "."})
            t = data.get("timings", {})
            row = {"sessions": n, "round": rnd, "session": i, "returning": rnd > 0,
                   "cache_n": t.get("cache_n"), "prompt_n": t.get("prompt_n"),
                   "prompt_ms": round(t.get("prompt_ms", 0), 1), "wall_s": round(wall, 2)}
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    out = {}
    for n in sorted({r["sessions"] for r in rows}):
        ret = [r for r in rows if r["sessions"] == n and r["returning"]]
        cold = [r for r in rows if r["sessions"] == n and not r["returning"]]
        if not ret:
            continue
        out[n] = {
            "cold_prompt_ms_median": statistics.median(r["prompt_ms"] for r in cold),
            "returning_prompt_ms_median": statistics.median(r["prompt_ms"] for r in ret),
            "returning_wall_s_median": statistics.median(r["wall_s"] for r in ret),
            "returning_hits": sum(1 for r in ret if (r["cache_n"] or 0) > r["prompt_n"]),
            "returning_turns": len(ret),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True)
    p.add_argument("--sessions", type=int, nargs="+", default=[2, 4, 8])
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--prompt-tokens", type=int, default=2000)
    p.add_argument("--distinct", type=int, default=0,
                   help="instead of the TTFT runs, send N distinct one-turn prompts to fill the cache")
    p.add_argument("--label", default="")
    p.add_argument("--out", default="")
    p.add_argument("--timeout", type=float, default=240)
    args = p.parse_args()

    nonce = f"{args.label or 'run'}-{int(time.time())}"
    if args.distinct:
        rows = run_sessions(args.url, args.distinct, 1, args.prompt_tokens, nonce, args.timeout)
        result = {"label": args.label, "distinct": args.distinct, "rows": rows}
    else:
        rows = []
        for n in args.sessions:
            rows += run_sessions(args.url, n, args.rounds, args.prompt_tokens, nonce, args.timeout)
        result = {"label": args.label, "prompt_tokens": args.prompt_tokens,
                  "summary": summarize(rows), "rows": rows}
        print(json.dumps(result["summary"], indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
