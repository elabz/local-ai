#!/usr/bin/env python3
"""Secret-free sustained chat load probe; stores only aggregate outcomes."""

import argparse
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request


def post(url: str, model: str, timeout: float, api_key: str, request_interval: float) -> tuple[int, float]:
    # Fixed synthetic text only; neither request nor response content is logged.
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Return the word ready, then count from one to twenty."}],
        "max_tokens": 64,
        "stream": False,
    }).encode()
    started = time.monotonic()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            result = (response.status, time.monotonic() - started)
    except urllib.error.HTTPError as error:
        error.read()
        result = (error.code, time.monotonic() - started)
    except Exception:
        result = (0, time.monotonic() - started)
    if request_interval:
        time.sleep(request_interval)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="heartcode-chat-sfw")
    parser.add_argument("--duration", type=float, default=90, help="Must span at least five watchdog intervals")
    parser.add_argument("--watchdog-interval", type=float, default=15)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--api-key-env", help="Read the API key from this environment variable")
    parser.add_argument("--request-interval", type=float, default=0.5, help="Per-worker delay to prevent retry amplification")
    args = parser.parse_args()
    if args.duration < args.watchdog_interval * 5:
        parser.error("duration must span at least five watchdog intervals")

    deadline = time.monotonic() + args.duration
    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    if args.api_key_env and not api_key:
        parser.error("configured API key environment variable is absent")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = set()
        while time.monotonic() < deadline or pending:
            while time.monotonic() < deadline and len(pending) < args.workers:
                pending.add(pool.submit(post, args.url, args.model, args.timeout, api_key, args.request_interval))
            done, pending = concurrent.futures.wait(
                pending, timeout=0.25, return_when=concurrent.futures.FIRST_COMPLETED,
            )
            results.extend(job.result() for job in done)

    statuses = {}
    for status, _ in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    latencies = sorted(duration for _, duration in results)
    summary = {
        "requests": len(results), "statuses": statuses,
        "latency_seconds_min": round(latencies[0], 3) if latencies else None,
        "latency_seconds_max": round(latencies[-1], 3) if latencies else None,
        "latency_seconds_p50": round(latencies[len(latencies) // 2], 3) if latencies else None,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if results and all(status == 200 for status, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
