#!/usr/bin/env python3
"""Benchmark script for GPU inference server."""

import argparse
import asyncio
import statistics
import time
from typing import List

import httpx


async def single_request(
    client: httpx.AsyncClient,
    url: str,
    prompt: str,
    max_tokens: int,
) -> dict:
    """Send a single inference request."""
    start = time.time()

    response = await client.post(
        f"{url}/v1/completions",
        json={
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0.8,
        },
        timeout=120.0,
    )

    elapsed = time.time() - start
    data = response.json()

    tokens_generated = data.get("usage", {}).get("completion_tokens", 0)

    return {
        "elapsed": elapsed,
        "tokens": tokens_generated,
        "tokens_per_second": tokens_generated / elapsed if elapsed > 0 else 0,
        "status": response.status_code,
    }


async def run_benchmark(
    url: str,
    prompt: str,
    max_tokens: int,
    num_requests: int,
    concurrency: int,
) -> List[dict]:
    """Run benchmark with specified concurrency."""
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async def limited_request(client: httpx.AsyncClient):
        async with semaphore:
            return await single_request(client, url, prompt, max_tokens)

    async with httpx.AsyncClient() as client:
        # Warm up
        print("Warming up...")
        await single_request(client, url, prompt, 10)

        # Run benchmark
        print(f"Running {num_requests} requests with concurrency {concurrency}...")
        start = time.time()

        tasks = [limited_request(client) for _ in range(num_requests)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_elapsed = time.time() - start

    # Filter out exceptions
    valid_results = [r for r in results if isinstance(r, dict)]
    errors = len(results) - len(valid_results)

    return valid_results, total_elapsed, errors


def print_results(results: List[dict], total_elapsed: float, errors: int):
    """Print benchmark results."""
    if not results:
        print("No successful requests!")
        return

    latencies = [r["elapsed"] for r in results]
    tokens_per_sec = [r["tokens_per_second"] for r in results]
    total_tokens = sum(r["tokens"] for r in results)

    print("\n" + "=" * 50)
    print("BENCHMARK RESULTS")
    print("=" * 50)

    print(f"\nRequests:")
    print(f"  Total:      {len(results) + errors}")
    print(f"  Successful: {len(results)}")
    print(f"  Errors:     {errors}")

    print(f"\nLatency (seconds):")
    print(f"  Min:    {min(latencies):.2f}")
    print(f"  Max:    {max(latencies):.2f}")
    print(f"  Mean:   {statistics.mean(latencies):.2f}")
    print(f"  Median: {statistics.median(latencies):.2f}")
    print(f"  Std:    {statistics.stdev(latencies):.2f}" if len(latencies) > 1 else "")

    print(f"\nTokens/second:")
    print(f"  Min:    {min(tokens_per_sec):.1f}")
    print(f"  Max:    {max(tokens_per_sec):.1f}")
    print(f"  Mean:   {statistics.mean(tokens_per_sec):.1f}")

    print(f"\nThroughput:")
    print(f"  Total tokens:     {total_tokens}")
    print(f"  Total time:       {total_elapsed:.2f}s")
    print(f"  Requests/second:  {len(results) / total_elapsed:.2f}")
    print(f"  Tokens/second:    {total_tokens / total_elapsed:.1f}")

    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Benchmark GPU inference server")
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Server URL",
    )
    parser.add_argument(
        "--prompt",
        default="Write a short story about a robot learning to love:",
        help="Prompt to use",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100,
        help="Max tokens to generate",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=10,
        help="Number of requests",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Concurrent requests",
    )

    args = parser.parse_args()

    print(f"Benchmarking {args.url}")
    print(f"Prompt: {args.prompt[:50]}...")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")

    results, total_elapsed, errors = asyncio.run(
        run_benchmark(
            url=args.url,
            prompt=args.prompt,
            max_tokens=args.max_tokens,
            num_requests=args.requests,
            concurrency=args.concurrency,
        )
    )

    print_results(results, total_elapsed, errors)


if __name__ == "__main__":
    main()
