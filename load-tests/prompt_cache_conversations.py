#!/usr/bin/env python3
"""Append-only chat conversations up to a context budget (serve-prompt-cache-reuse §3).

Drives multi-turn conversations through LiteLLM the way HeartCode's
`stable-prompt-prefix` layout will. Each prompt has three parts:
- a fixed frame (system prompt);
- a history that only grows;
- a per-turn memory block inside the final user message.

When the next turn would not fit the budget, the history is cut back to the
newest messages within `--keep-share` of the room (a "rebuild").

Every turn sends `X-Session-Id`, so affinity keeps the conversation on one
replica, and records:
- tokens reused and evaluated, from the streamed usage;
- time to first token;
- the deployment that served it (`x-litellm-model-id`).

Meanwhile Pea is sampled over SSH: per-GPU VRAM, chat container memory, and
at the end kernel OOM kills and container or `llama-server` restarts.

The bundle holds no prompt or reply text and no key.

    LITELLM_KEY=sk-... python3 prompt_cache_conversations.py \\
        --model heartcode-chat-sfw --conversations 2 --turns 30 \\
        --output results/prompt-cache-sfw-8k.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import httpx

WORDS = (
    "harbour lantern tide ferry dock rope sail gull storm fog captain river market bread salt "
    "letter promise winter bridge tower orchard well lamp bell road inn traveller map compass "
    "journal sister brother friend stranger song festival boat island north south east west "
    "morning evening quiet distant bright careful gentle sudden old new small great hidden"
).split()


def prose(rng: random.Random, words: int) -> str:
    sentences, current = [], []
    for _ in range(words):
        current.append(rng.choice(WORDS))
        if len(current) >= rng.randint(8, 16):
            sentences.append(" ".join(current).capitalize() + ".")
            current = []
    if current:
        sentences.append(" ".join(current).capitalize() + ".")
    return " ".join(sentences)


def pea(ssh: str, command: str, timeout: float = 20) -> str:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ssh, command],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout


def pea_state(ssh: str) -> dict[str, Any]:
    out = pea(
        ssh,
        "for c in $(docker ps --format '{{.Names}}' | grep -E '^pea-gpu-[0-9]+$'); do "
        "echo \"$c $(docker inspect -f '{{.RestartCount}} {{.State.StartedAt}}' $c) "
        "$(docker exec $c pgrep -o llama-server)\"; done",
    )
    state = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4:
            state[parts[0]] = {"restarts": int(parts[1]), "started": parts[2], "llama_pid": parts[3]}
    return state


async def sampler(ssh: str, interval: float, samples: list, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            out = await asyncio.to_thread(
                pea, ssh,
                "nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits; "
                "echo ---; docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E '^pea-gpu-[0-9]+ '",
            )
            gpu_part, _, mem_part = out.partition("---")
            gpus = {}
            for line in gpu_part.strip().splitlines():
                idx, used, total = [x.strip() for x in line.split(",")]
                gpus[idx] = {"used": int(used), "total": int(total)}
            mem = {}
            for line in mem_part.strip().splitlines():
                name, usage = line.split(" ", 1)
                mem[name] = usage.strip()
            samples.append({"t": time.time(), "gpus": gpus, "mem": mem})
        except Exception as exc:  # sampling must not stop the run
            samples.append({"t": time.time(), "error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def turn(client: httpx.AsyncClient, args, session: str, system: str, history: list,
               user: str) -> dict[str, Any]:
    body = {
        "model": args.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": args.max_tokens,
        "temperature": 0.8,
        "messages": [{"role": "system", "content": system}, *history, {"role": "user", "content": user}],
    }
    start = time.time()
    first = None
    usage = None
    reply = ""
    async with client.stream("POST", "/v1/chat/completions", json=body,
                             headers={"X-Session-Id": session}) as response:
        if response.status_code != 200:
            text = (await response.aread()).decode(errors="ignore")[:200]
            return {"error": f"HTTP {response.status_code}", "detail": text, "seconds": time.time() - start}
        deployment = response.headers.get("x-litellm-model-id")
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    if first is None:
                        first = time.time()
                    reply += text
    details = (usage or {}).get("prompt_tokens_details") or {}
    prompt = (usage or {}).get("prompt_tokens")
    cached = details.get("cached_tokens")
    return {
        "deployment": deployment,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "evaluated_tokens": (prompt - cached) if isinstance(prompt, int) and isinstance(cached, int) else None,
        "completion_tokens": (usage or {}).get("completion_tokens"),
        "first_token_seconds": (first - start) if first else None,
        "seconds": time.time() - start,
        "_reply": reply,
    }


async def conversation(client, args, index: int, results: list) -> None:
    rng = random.Random(f"{args.model}-{index}-{args.seed}")
    session = f"prompt-cache-qual-{args.seed}-{args.model}-{index}"
    system = "You are Mara, a ferry captain in Bellweather. Stay in character. " + prose(rng, args.frame_words)
    history: list[dict[str, str]] = []
    last_prompt = 0
    growth = args.max_tokens + 200  # a guess until the first turns measure it
    for n in range(args.turns):
        memories = "\n".join(f"- {prose(rng, 40)}" for _ in range(args.memory_lines))
        said = f"Turn {n}: " + prose(rng, rng.randint(20, 60))
        user = f"[Context for your next reply. The user did not say this.]\n{memories}\n[End of context]\n\n{said}"
        rebuild = False
        if last_prompt and last_prompt + growth > args.budget - args.response_buffer:
            # Keep the newest messages within keep-share of the room the history had.
            keep_tokens = (args.budget - args.response_buffer - (last_prompt - history_tokens(history))) * args.keep_share
            kept, total = [], 0
            for message in reversed(history):
                size = len(message["content"]) // 4
                if total + size > keep_tokens and len(kept) >= args.min_messages:
                    break
                kept.insert(0, message)
                total += size
            while kept and kept[0]["role"] != "user":
                kept.pop(0)
            history = kept
            rebuild = True
        result = await turn(client, args, session, system, history, user)
        reply = result.pop("_reply", "")
        result.update({"conversation": index, "turn": n, "rebuild": rebuild, "history_messages": len(history)})
        results.append(result)
        print(json.dumps({k: result.get(k) for k in ("conversation", "turn", "deployment", "prompt_tokens",
                                                     "cached_tokens", "first_token_seconds", "rebuild", "error")}),
              flush=True)
        if "error" in result:
            continue
        history += [{"role": "user", "content": said}, {"role": "assistant", "content": reply or "..."}]
        if isinstance(result.get("prompt_tokens"), int):
            if last_prompt and not rebuild:
                growth = max(growth // 2, result["prompt_tokens"] - last_prompt + (result.get("completion_tokens") or 0))
            last_prompt = result["prompt_tokens"] + (result.get("completion_tokens") or 0)
        await asyncio.sleep(args.think_seconds)


def history_tokens(history: list) -> int:
    return sum(len(m["content"]) // 4 for m in history)


def pct(values: list[float], q: float):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(q * (len(values) - 1))))], 2)


def summarize(results: list, samples: list, before: dict, after: dict, ooms: int) -> dict:
    ok = [r for r in results if "error" not in r]
    ordinary = [r for r in ok if not r["rebuild"] and r["turn"] > 0]
    rebuilds = [r for r in ok if r["rebuild"]]
    reused = sum(r["cached_tokens"] or 0 for r in ordinary if r["cached_tokens"] is not None)
    evaluated = sum(r["evaluated_tokens"] or 0 for r in ordinary if r["evaluated_tokens"] is not None)
    same = 0
    pairs = 0
    by_conv: dict[int, list] = {}
    for r in ok:
        by_conv.setdefault(r["conversation"], []).append(r)
    for turns in by_conv.values():
        for a, b in zip(turns, turns[1:]):
            pairs += 1
            same += a["deployment"] == b["deployment"]
    headroom = {}
    peak_mem = {}
    for s in samples:
        for idx, g in s.get("gpus", {}).items():
            free = g["total"] - g["used"]
            headroom[idx] = min(headroom.get(idx, free), free)
        for name, usage in s.get("mem", {}).items():
            peak_mem.setdefault(name, []).append(usage)
    return {
        "turns": len(results),
        "errors": len(results) - len(ok),
        "max_prompt_tokens": max((r["prompt_tokens"] or 0) for r in ok) if ok else None,
        "ordinary_turns": len(ordinary),
        "rebuild_turns": len(rebuilds),
        "ordinary_first_token_p50": pct([r["first_token_seconds"] for r in ordinary if r["first_token_seconds"]], 0.5),
        "ordinary_first_token_p95": pct([r["first_token_seconds"] for r in ordinary if r["first_token_seconds"]], 0.95),
        "rebuild_first_token_p50": pct([r["first_token_seconds"] for r in rebuilds if r["first_token_seconds"]], 0.5),
        "rebuild_first_token_p95": pct([r["first_token_seconds"] for r in rebuilds if r["first_token_seconds"]], 0.95),
        "ordinary_reuse_rate": round(reused / (reused + evaluated), 4) if reused + evaluated else None,
        "ordinary_evaluated_tokens_median": (
            statistics.median([r["evaluated_tokens"] for r in ordinary if r["evaluated_tokens"] is not None])
            if ordinary else None),
        "same_replica_consecutive": f"{same}/{pairs}",
        "min_vram_headroom_mib": headroom,
        "container_memory_last": {k: v[-1] for k, v in peak_mem.items()},
        "container_restarts_or_llama_exits": {
            name: {"before": before.get(name), "after": after.get(name)}
            for name in sorted(set(before) | set(after))
            if before.get(name) != after.get(name)
        },
        "kernel_oom_kills": ooms,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://192.168.70.152:4000")
    parser.add_argument("--api-key-env", default="LITELLM_KEY")
    parser.add_argument("--model", required=True)
    parser.add_argument("--conversations", type=int, default=2)
    parser.add_argument("--parallel", type=int, default=1, help="conversations at once")
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--budget", type=int, default=8192)
    parser.add_argument("--response-buffer", type=int, default=819)
    parser.add_argument("--keep-share", type=float, default=0.5)
    parser.add_argument("--min-messages", type=int, default=5)
    parser.add_argument("--frame-words", type=int, default=1100, help="~1.5k tokens")
    parser.add_argument("--memory-lines", type=int, default=10, help="~550 tokens per turn")
    parser.add_argument("--max-tokens", type=int, default=250)
    parser.add_argument("--think-seconds", type=float, default=3)
    parser.add_argument("--seed", default=datetime.now(timezone.utc).strftime("%Y%m%d%H%M"))
    parser.add_argument("--pea-ssh", default="192.168.70.144")
    parser.add_argument("--sample-seconds", type=float, default=10)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    key = os.environ[args.api_key_env]
    started = datetime.now(timezone.utc)
    before = await asyncio.to_thread(pea_state, args.pea_ssh)
    samples: list = []
    stop = asyncio.Event()
    sampling = asyncio.create_task(sampler(args.pea_ssh, args.sample_seconds, samples, stop))
    results: list = []
    timeout = httpx.Timeout(connect=10, read=300, write=30, pool=30)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout,
                                 headers={"Authorization": f"Bearer {key}"}) as client:
        queue = list(range(args.conversations))

        async def worker():
            while queue:
                await conversation(client, args, queue.pop(0), results)

        await asyncio.gather(*(worker() for _ in range(args.parallel)))
    stop.set()
    await sampling
    after = await asyncio.to_thread(pea_state, args.pea_ssh)
    since = started.strftime("%Y-%m-%d %H:%M:%S")
    ooms_out = await asyncio.to_thread(
        pea, args.pea_ssh, f"journalctl -k --since '{since} UTC' 2>/dev/null | grep -c 'Out of memory' || true")
    ooms = int((ooms_out.strip() or "0").splitlines()[-1])
    bundle = {
        "change": "serve-prompt-cache-reuse §3",
        "started": started.isoformat(),
        "finished": datetime.now(timezone.utc).isoformat(),
        "settings": {k: v for k, v in vars(args).items() if k not in ("api_key_env", "output")},
        "summary": summarize(results, samples, before, after, ooms),
        "turns": results,
        "samples": samples,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(bundle, fh, indent=1)
    print(json.dumps(bundle["summary"], indent=1))
    return 0 if bundle["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
