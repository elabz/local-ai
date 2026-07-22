"""Bounded, content-free live TTS probe for custom-voice build interference."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    workload: str
    latency_seconds: float
    status: int
    ogg_opus: bool


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("probe_results_missing")
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def summarize(results: list[ProbeResult], *, baseline_p95_seconds: float) -> dict[str, object]:
    if not results or baseline_p95_seconds <= 0:
        raise ValueError("probe_results_invalid")
    successful = [item for item in results if item.status == 200 and item.ogg_opus]
    p95 = percentile([item.latency_seconds for item in results], 0.95)
    error_rate = 1 - (len(successful) / len(results))
    latency_limit = baseline_p95_seconds * 1.25
    return {
        "schema_version": "custom-voice-live-speech-probe.v1",
        "request_count": len(results),
        "success_count": len(successful),
        "error_rate": error_rate,
        "p95_latency_seconds": p95,
        "baseline_p95_seconds": baseline_p95_seconds,
        "max_allowed_p95_seconds": latency_limit,
        "opus_40k_valid_count": sum(item.ogg_opus for item in results),
        "workloads": {name: sum(item.workload == name for item in results) for name in sorted({item.workload for item in results})},
        "outcome": "pass" if error_rate == 0 and p95 <= latency_limit and len(successful) == len(results) else "reject",
    }


def _request(*, url: str, api_key: str, workload: str, voice: str, timeout: float) -> ProbeResult:
    # Fixed synthetic prompts are intentionally not emitted in results or logs.
    prompts = {
        "quick-chat": "Please confirm that the live speech path remains clear and responsive.",
        "character": "The lanterns glowed softly while the evening wind moved through the trees.",
    }
    body = json.dumps({
        "model": "kokoro",
        "voice": voice,
        "input": prompts[workload],
        "response_format": "opus",
        "encoding_profile": "opus-40k",
    }).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    started = time.monotonic()
    status = 0
    content = b""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            content = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
    except (OSError, TimeoutError):
        pass
    return ProbeResult(workload, time.monotonic() - started, status, content.startswith(b"OggS"))


def run(*, url: str, api_key: str, requests: int, concurrency: int, timeout: float, baseline_p95_seconds: float) -> dict[str, object]:
    if not api_key or requests < 2 or concurrency < 1 or concurrency > 4 or requests > 40:
        raise ValueError("probe_configuration_invalid")
    work = [("quick-chat", "af_heart") if index % 2 == 0 else ("character", "af_bella") for index in range(requests)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_request, url=url, api_key=api_key, workload=workload, voice=voice, timeout=timeout) for workload, voice in work]
        results = [future.result() for future in futures]
    return summarize(results, baseline_p95_seconds=baseline_p95_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--baseline-p95", type=float, required=True)
    arguments = parser.parse_args()
    result = run(
        url=arguments.url,
        api_key=os.environ.get("SPEECH_DIRECT_API_KEY", ""),
        requests=arguments.requests,
        concurrency=arguments.concurrency,
        timeout=arguments.timeout,
        baseline_p95_seconds=arguments.baseline_p95,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
