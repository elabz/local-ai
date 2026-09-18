#!/usr/bin/env python3
"""Fail when the PEA compose memory limits do not fit in the host's RAM.

Change bound-llama-host-prompt-cache (design D4). On 2026-09-18 the chat
limits alone summed to 42 GiB on a 31 GB host, and the kernel OOM-killed
llama-server twice. This check makes "add one more worker" fail CI instead.

Budget, declared in the compose file itself:

  x-host-memory:
    host_ram_mib: 32023
    os_reserve_mib: 2048

Rules, for every service started by a plain `docker compose up -d` (services
behind `profiles:` are opt-in and not counted):
  - mem_limit is set;
  - memswap_limit is set, >= mem_limit, and at most 512 MiB above it;
  - the gpu-server-N chat workers all share one mem_limit/memswap_limit;
  - the sum of mem_limit <= host_ram_mib - os_reserve_mib.

Usage:
  check-memory-budget.py [--compose gpu-server/docker-compose.yml]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

DEFAULT_COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
MAX_SWAP_HEADROOM_MIB = 512
CHAT_WORKER = re.compile(r"^gpu-server-\d+$")
UNITS = {"": 1 / (1024 * 1024), "b": 1 / (1024 * 1024), "k": 1 / 1024, "m": 1, "g": 1024}


def to_mib(value) -> float:
    """Compose size (bytes int, or '512m', '2g', '1024k', '${X:-768m}') -> MiB."""
    if isinstance(value, (int, float)):
        return value / (1024 * 1024)
    text = str(value).strip()
    env = re.fullmatch(r"\$\{[^:}]+:-([^}]+)\}", text)
    if env:
        text = env.group(1)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([bkmg]?)b?", text.lower())
    if not match:
        raise ValueError(f"unparseable size {value!r}")
    return float(match.group(1)) * UNITS[match.group(2)]


def check(compose: dict) -> tuple[list[str], list[tuple[str, float, float]], float]:
    """Return (problems, rows of (service, mem_mib, swap_mib), budget_mib)."""
    problems: list[str] = []
    host = compose.get("x-host-memory") or {}
    try:
        budget = float(host["host_ram_mib"]) - float(host["os_reserve_mib"])
    except (KeyError, TypeError, ValueError):
        return ["x-host-memory must declare host_ram_mib and os_reserve_mib"], [], 0.0

    rows: list[tuple[str, float, float]] = []
    chat_configs: dict[tuple[float, float], list[str]] = {}
    for name, svc in (compose.get("services") or {}).items():
        if svc.get("profiles"):
            continue
        if "mem_limit" not in svc:
            problems.append(f"{name}: no mem_limit")
            continue
        mem = to_mib(svc["mem_limit"])
        if "memswap_limit" not in svc:
            problems.append(f"{name}: no memswap_limit")
            swap = mem
        else:
            swap = to_mib(svc["memswap_limit"])
            if swap < mem:
                problems.append(f"{name}: memswap_limit {swap:.0f} MiB < mem_limit {mem:.0f} MiB")
            elif swap - mem > MAX_SWAP_HEADROOM_MIB:
                problems.append(f"{name}: memswap_limit allows {swap - mem:.0f} MiB of swap "
                                f"(max {MAX_SWAP_HEADROOM_MIB})")
        rows.append((name, mem, swap))
        if CHAT_WORKER.match(name):
            chat_configs.setdefault((mem, swap), []).append(name)

    if len(chat_configs) > 1:
        detail = "; ".join(f"{m:.0f}/{s:.0f} MiB: {', '.join(names)}"
                           for (m, s), names in sorted(chat_configs.items()))
        problems.append(f"chat workers differ in memory configuration ({detail})")

    total = sum(mem for _, mem, _ in rows)
    if total > budget:
        problems.append(f"sum of mem_limit {total:.0f} MiB exceeds budget {budget:.0f} MiB "
                        f"(host_ram_mib - os_reserve_mib) by {total - budget:.0f} MiB")
    return problems, rows, budget


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    args = parser.parse_args()

    compose = yaml.safe_load(args.compose.read_text())
    problems, rows, budget = check(compose)
    for name, mem, swap in sorted(rows, key=lambda r: -r[1]):
        print(f"  {name:28} mem_limit {mem:7.0f} MiB  memswap_limit {swap:7.0f} MiB")
    print(f"  {'total':28} mem_limit {sum(r[1] for r in rows):7.0f} MiB  budget {budget:.0f} MiB")
    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        print("OK: PEA memory limits fit the host budget")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
