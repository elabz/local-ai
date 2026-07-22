"""Live isolated LiteLLM routing contract; requires the disposable test stack."""

import os

import httpx
import pytest

BASE_URL = os.getenv("LITELLM_GPU_TEST_URL")
TEST_KEY = os.getenv("LITELLM_GPU_TEST_KEY", "test-gpu-routing-key")

pytestmark = pytest.mark.skipif(not BASE_URL, reason="isolated LiteLLM stack is not configured")


def request(path: str, **kwargs):
    headers = {"Authorization": f"Bearer {TEST_KEY}"}
    return httpx.request(kwargs.pop("method", "GET"), f"{BASE_URL}{path}", headers=headers, timeout=20, **kwargs)


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
