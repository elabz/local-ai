"""Tests for scripts/check-memory-budget.py (bound-llama-host-prompt-cache, design D4)."""

import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-memory-budget.py"
spec = importlib.util.spec_from_file_location("check_memory_budget", SCRIPT)
assert spec is not None and spec.loader is not None
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)

HOST = {"host_ram_mib": 10000, "os_reserve_mib": 2000}


def compose(services, host=HOST):
    return {"x-host-memory": host, "services": services}


def svc(mem="1024m", swap="1536m", **extra):
    return {"mem_limit": mem, "memswap_limit": swap, **extra}


@pytest.mark.parametrize("value,mib", [
    ("512m", 512), ("2g", 2048), ("1024k", 1), ("${X:-768m}", 768), (1073741824, 1024), ("3072M", 3072),
])
def test_to_mib(value, mib):
    assert budget.to_mib(value) == mib


def test_within_budget_passes():
    problems, rows, total_budget = budget.check(compose({"a": svc(), "b": svc()}))
    assert problems == []
    assert total_budget == 8000
    assert len(rows) == 2


def test_over_budget_fails():
    problems, _, _ = budget.check(compose({f"s{i}": svc("2048m", "2560m") for i in range(4)}))
    assert any("exceeds budget" in p and "by 192 MiB" in p for p in problems)


def test_missing_mem_limit_fails():
    problems, _, _ = budget.check(compose({"a": {"image": "x"}}))
    assert problems == ["a: no mem_limit"]


def test_memswap_below_limit_fails():
    problems, _, _ = budget.check(compose({"a": svc("1024m", "512m")}))
    assert any("memswap_limit 512 MiB < mem_limit 1024 MiB" in p for p in problems)


def test_too_much_swap_fails():
    problems, _, _ = budget.check(compose({"a": svc("1024m", "2048m")}))
    assert any("allows 1024 MiB of swap" in p for p in problems)


def test_chat_workers_must_match():
    problems, _, _ = budget.check(compose({
        "gpu-server-1": svc("2048m", "2560m"),
        "gpu-server-2": svc("2048m", "2560m"),
        "gpu-server-6": svc("1024m", "1536m"),
    }))
    assert any("chat workers differ" in p and "gpu-server-6" in p for p in problems)


def test_profiled_services_are_not_counted():
    problems, rows, _ = budget.check(compose({
        "a": svc(),
        "canary": {"image": "x", "profiles": ["canary"]},
    }))
    assert problems == []
    assert [r[0] for r in rows] == ["a"]


def test_missing_host_block_fails():
    problems, _, _ = budget.check({"services": {"a": svc()}})
    assert problems == ["x-host-memory must declare host_ram_mib and os_reserve_mib"]


def test_yaml_anchors_are_resolved():
    text = """
x-host-memory: {host_ram_mib: 10000, os_reserve_mib: 2000}
x-common: &common
  mem_limit: 2048m
  memswap_limit: 2560m
services:
  gpu-server-1:
    <<: *common
  gpu-server-2:
    <<: *common
"""
    problems, rows, _ = budget.check(yaml.safe_load(text))
    assert problems == []
    assert [r[1] for r in rows] == [2048, 2048]
