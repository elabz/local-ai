#!/usr/bin/env python3
"""Safe aggregate benchmark for isolated llama.cpp model canaries."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONTEXTS = (4096, 8192, 16384, 24576, 32768)
SAFE_IDENTITY_KEYS = {
    "model_repo", "model_revision", "model_file", "model_sha256",
    "quantization", "license", "llama_commit", "llama_build", "gpu_uuid",
}


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    rank = fraction * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def safe_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(SAFE_IDENTITY_KEYS) if key in value}


def context_plan(max_context: int) -> list[int]:
    return [size for size in CONTEXTS if size <= max_context]


def gate(role: str, context: int, speeds: list[float], failures: int) -> dict[str, Any]:
    floor = 10.0 if role == "sfw" else 12.0
    required_context = 16384 if role == "sfw" else context
    p10 = percentile(speeds, 0.10) if speeds else 0.0
    passed = failures == 0 and context >= required_context and p10 >= floor
    return {"floor_tps": floor, "p10_tps": round(p10, 3), "passed": passed}


def request_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[dict[str, Any], float]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed, time.monotonic() - started


def run(args: argparse.Namespace) -> dict[str, Any]:
    identity = safe_identity(json.loads(Path(args.identity).read_text(encoding="utf-8")))
    speeds: list[float] = []
    latencies: list[float] = []
    prompt_speeds: list[float] = []
    prompt_tokens: list[int] = []
    request_failures = 0
    validation_failures = 0
    padding = " neutral-context" * args.padding_words
    payload = {
        "model": "canary", "temperature": 0, "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": args.synthetic_prompt + padding}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "canary_probe", "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["answer", "evidence"],
                "properties": {"answer": {"type": "string"}, "evidence": {"type": "string"}},
            },
        }},
    }
    for _ in range(args.requests):
        try:
            data, elapsed = request_json(f"{args.url}/v1/chat/completions", payload, args.timeout)
            timings = data.get("timings") or {}
            usage = data.get("usage") or {}
            generated = float(usage.get("completion_tokens") or 0)
            prompt_tokens.append(int(usage.get("prompt_tokens") or 0))
            speeds.append(float(timings.get("predicted_per_second") or (generated / elapsed)))
            if timings.get("prompt_per_second") is not None:
                prompt_speeds.append(float(timings["prompt_per_second"]))
            latencies.append(elapsed)
            if args.role == "sfw":
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    validation_failures += 1
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            request_failures += 1
    failures = request_failures + validation_failures
    result = {
        "schema_version": "model-canary-benchmark.v1",
        "identity": identity,
        "role": args.role,
        "context": args.context,
        "requests": args.requests,
        "successes": len(speeds),
        "failures": failures,
        "request_failures": request_failures,
        "validation_failures": validation_failures,
        "prompt_tokens_mean": round(statistics.mean(prompt_tokens), 1) if prompt_tokens else None,
        "decode_tps": {
            "p10": round(percentile(speeds, 0.10), 3) if speeds else 0.0,
            "median": round(statistics.median(speeds), 3) if speeds else 0.0,
            "mean": round(statistics.mean(speeds), 3) if speeds else 0.0,
        },
        "latency_seconds": {
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
        },
        "prompt_tps_mean": round(statistics.mean(prompt_speeds), 3) if prompt_speeds else None,
        "gate": gate(args.role, args.context, speeds, failures),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--role", choices=("sfw", "nsfw"), required=True)
    parser.add_argument("--context", type=int, choices=CONTEXTS, required=True)
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--synthetic-prompt", default='Return JSON with keys "answer" and "evidence" explaining conduit fill calculations.')
    parser.add_argument("--padding-words", type=int, default=0)
    args = parser.parse_args()
    result = run(args)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["gate"]["passed"] else 1)


if __name__ == "__main__":
    main()
