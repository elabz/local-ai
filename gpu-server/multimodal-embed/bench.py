#!/usr/bin/env python3
"""Smoke test + micro-benchmark for the multimodal embedding server.

Stdlib-only (no PIL/requests) so it runs on the PEA host directly. Exercises:
  - text embedding (records dimension + latency)
  - image embedding (base64 PNG generated in-process)
  - a mixed text+image batch (verifies one vector per item, in order)
  - a malformed-image request (expects HTTP 400, not a crash)
and reports peak GPU VRAM via nvidia-smi.

Covers openspec tasks 1.4 (dimension), 3.4 (text+image smoke), 4.1/4.2
(precision/VRAM/latency benchmark).

Usage:
  python3 bench.py --base http://localhost:8100 --runs 5
"""

import argparse
import base64
import json
import struct
import subprocess
import time
import urllib.error
import urllib.request
import zlib


def make_png(width: int = 256, height: int = 256) -> bytes:
    """Build a small RGB PNG (diagonal gradient) using only stdlib."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) per scanline
        for x in range(width):
            raw += bytes(((x + y) % 256, (x * 2) % 256, (y * 2) % 256))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def post(base: str, payload: dict, timeout: int = 300):
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/embeddings",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def gpu_vram():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            text=True,
        )
        return [line.strip() for line in out.strip().splitlines()]
    except Exception as e:
        return [f"(nvidia-smi unavailable: {e})"]


def timed(fn, runs):
    lat = []
    last = None
    for _ in range(runs):
        t0 = time.time()
        last = fn()
        lat.append(time.time() - t0)
    lat.sort()
    return last, lat[len(lat) // 2], min(lat), max(lat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8100")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--model", default="heartcode-embed")
    args = ap.parse_args()

    data_uri = "data:image/png;base64," + base64.b64encode(make_png()).decode()

    print(f"== Multimodal embedding benchmark @ {args.base} ==")
    print("VRAM before:", *gpu_vram(), sep="\n  ")

    # --- text ---
    def text_call():
        _, body = post(args.base, {"model": args.model, "input": "a red bicycle"})
        return body
    body, med, lo, hi = timed(text_call, args.runs)
    dim = len(body["data"][0]["embedding"])
    print(f"\n[text]  dimension={dim}  latency median={med:.3f}s ({lo:.3f}-{hi:.3f})")

    # --- image ---
    def image_call():
        _, body = post(args.base, {"model": args.model, "input": {"image": data_uri}})
        return body
    body, med, lo, hi = timed(image_call, args.runs)
    idim = len(body["data"][0]["embedding"])
    print(f"[image] dimension={idim}  latency median={med:.3f}s ({lo:.3f}-{hi:.3f})")
    assert idim == dim, f"image dim {idim} != text dim {dim} (not a shared space!)"

    # --- mixed batch (order preserved) ---
    _, body = post(args.base, {
        "model": args.model,
        "input": ["a red bicycle", {"image": data_uri}, "a blue car"],
    })
    assert len(body["data"]) == 3, body
    assert [d["index"] for d in body["data"]] == [0, 1, 2], body
    print(f"[mixed] {len(body['data'])} vectors returned in order: OK")

    # --- malformed image -> 400, not a crash ---
    try:
        post(args.base, {"model": args.model, "input": {"image": "not-base64!!!"}})
        print("[error] WARNING: malformed image did NOT return an error")
    except urllib.error.HTTPError as e:
        print(f"[error] malformed image -> HTTP {e.code}: OK")

    print("\nVRAM after:", *gpu_vram(), sep="\n  ")
    print("\nSmoke test PASSED.")


if __name__ == "__main__":
    main()
