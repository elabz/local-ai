"""Live isolated LiteLLM routing contract; requires the disposable test stack.

    docker compose -f docker-compose.litellm-routing-test.yml up -d --wait
    LITELLM_GPU_TEST_URL=http://localhost:4410 pytest -q test_litellm_gpu_routing.py

The stack pins the same LiteLLM digest as litellm/docker-compose.yml, so what
passes here is what Prod's router does.
"""

import os
import re
from pathlib import Path

import httpx
import pytest
import yaml

BASE_URL = os.getenv("LITELLM_GPU_TEST_URL")
TEST_KEY = os.getenv("LITELLM_GPU_TEST_KEY", "test-gpu-routing-key")
# Host ports the fake backends publish (see docker-compose.litellm-routing-test.yml).
BUSY_STATS = os.getenv("LITELLM_GPU_TEST_BUSY_STATS", "http://localhost:4412/stats")
FLAKY_STATS = os.getenv("LITELLM_GPU_TEST_FLAKY_STATS", "http://localhost:4413/stats")
HEALTHY_STATS = os.getenv("LITELLM_GPU_TEST_HEALTHY_STATS", "http://localhost:4411/stats")

pytestmark = pytest.mark.skipif(not BASE_URL, reason="isolated LiteLLM stack is not configured")

PROBE_CHAT = "/v1/chat/completions probe"


def request(path: str, **kwargs):
    headers = {"Authorization": f"Bearer {TEST_KEY}"}
    return httpx.request(kwargs.pop("method", "GET"), f"{BASE_URL}{path}", headers=headers, timeout=30, **kwargs)


def chat(model: str):
    return request(
        "/v1/chat/completions",
        method="POST",
        json={"model": model, "messages": [{"role": "user", "content": "routing-probe"}], "max_tokens": 4},
    )


def stats(url: str) -> dict:
    return httpx.get(url, timeout=5).json()["counts"]


def cooldown_events() -> dict:
    """litellm_deployment_cooled_down_total samples keyed by api_base (0 when absent).

    Match the counter exactly: the exposition also carries a
    `..._cooled_down_created` timestamp gauge that must not be summed in."""
    text = request("/metrics/").text
    events = {}
    for line in text.splitlines():
        if not line.startswith("litellm_deployment_cooled_down_total{"):
            continue
        base = re.search(r'api_base="([^"]+)"', line)
        value = float(line.rsplit(" ", 1)[1])
        if base:
            events[base.group(1)] = events.get(base.group(1), 0.0) + value
    return events


def cooldowns_for(host: str) -> float:
    return sum(v for k, v in cooldown_events().items() if host in k)


# --- existing embedding contract ------------------------------------------------

def test_one_unavailable_replica_is_excluded_and_sibling_serves():
    health = request("/health", params={"model": "gpu-routing-one-down"})
    assert health.status_code == 200
    state = health.json()
    assert len(state["healthy_endpoints"]) == 1
    assert len(state["unhealthy_endpoints"]) == 1

    response = request(
        "/v1/embeddings",
        method="POST",
        json={"model": "gpu-routing-one-down", "input": "bounded integration probe"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["embedding"] == [0.25, 0.75]


def test_all_unavailable_returns_service_unavailable():
    health = request("/health", params={"model": "gpu-routing-all-down"})
    assert health.status_code == 200
    state = health.json()
    assert len(state["healthy_endpoints"]) == 0
    assert len(state["unhealthy_endpoints"]) == 2

    response = request(
        "/v1/embeddings",
        method="POST",
        json={"model": "gpu-routing-all-down", "input": "bounded integration probe"},
    )
    assert response.status_code == 503


# --- queue-busy-chat-backends -------------------------------------------------------

def test_router_policy_matches_production_base_config():
    """The disposable stack must exercise the router block Prod actually runs."""
    here = Path(__file__).resolve()
    test_router = yaml.safe_load(here.with_name("litellm_gpu_routing.yaml").read_text())["router_settings"]
    prod_router = yaml.safe_load((here.parents[3] / "litellm" / "config.base.yaml").read_text())["router_settings"]
    for key in ("allowed_fails", "cooldown_time", "num_retries", "routing_strategy", "allowed_fails_policy"):
        assert test_router[key] == prod_router[key], key
    # Without an explicit policy LiteLLM 1.81.9 ignores allowed_fails==3 (its
    # default) and cools a replica on its first 429 when a sibling exists.
    assert prod_router["allowed_fails_policy"]["RateLimitErrorAllowedFails"] >= 1000
    # Spec: cooldown needs >1 failure and lasts no longer than a generation.
    assert prod_router["allowed_fails"] >= 3
    assert prod_router["cooldown_time"] <= 30
    assert prod_router["num_retries"] >= 2


def test_busy_429_is_retried_on_sibling_and_does_not_cool_the_busy_replica():
    busy_before = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)
    cooled_before = cooldowns_for("gpu-test-busy")

    responses = [chat("chat-busy-with-sibling") for _ in range(6)]
    assert [r.status_code for r in responses] == [200] * 6
    assert all(r.json()["choices"][0]["message"]["content"] == "served-by-healthy" for r in responses)

    busy_after = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)
    # The busy replica was offered traffic and answered 429; the router moved on.
    assert busy_after > busy_before
    assert cooldowns_for("gpu-test-busy") == cooled_before


def test_single_busy_replica_surfaces_429_and_stays_routable():
    cooled_before = cooldowns_for("gpu-test-busy")

    first = chat("chat-busy-only")
    assert first.status_code == 429, first.text
    hits_after_first = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)

    # If the replica had been cooled the router would answer without contacting
    # it (no deployments available). It must still be tried.
    second = chat("chat-busy-only")
    assert second.status_code == 429, second.text
    assert stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0) > hits_after_first
    assert cooldowns_for("gpu-test-busy") == cooled_before
    assert "BACKEND_BUSY" in second.text or "busy" in second.text.lower()


def test_single_transient_503_is_retried_elsewhere_and_replica_remains_routable():
    cooled_before = cooldowns_for("gpu-test-flaky")

    responses = [chat("chat-flaky-with-sibling") for _ in range(8)]
    assert [r.status_code for r in responses] == [200] * 8

    counts = stats(FLAKY_STATS)
    assert counts.get(f"{PROBE_CHAT} 503", 0) == 1
    # After its one 503 the flaky replica kept receiving traffic and served it.
    assert counts.get(f"{PROBE_CHAT} 200", 0) >= 1, counts
    assert cooldowns_for("gpu-test-flaky") == cooled_before


def test_cooldown_metric_is_exposed_for_alerting():
    """monitoring alerts key on litellm_deployment_cooled_down; make sure the
    pinned image still exports it (name drift would silently mute the alert)."""
    text = request("/metrics/").text
    assert "litellm_deployment_cooled_down" in text
    assert "litellm_proxy_total_requests_metric" in text
