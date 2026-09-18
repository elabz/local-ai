"""/llama/metrics relays llama-server's Prometheus exposition through the wrapper."""

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import router  # noqa: E402

LLAMA_METRICS = (
    "# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.\n"
    "# TYPE llamacpp:prompt_tokens_total counter\n"
    "llamacpp:prompt_tokens_total 1234\n"
)


def _client(metrics):
    app = FastAPI()
    app.include_router(router)
    app.state.llama_client = SimpleNamespace(metrics=metrics)
    return TestClient(app)


def test_relays_llama_server_metrics():
    async def metrics():
        return LLAMA_METRICS

    response = _client(metrics).get("/llama/metrics")
    assert response.status_code == 200
    assert response.text == LLAMA_METRICS
    assert response.headers["content-type"].startswith("text/plain")


def test_unreachable_llama_server_is_503():
    async def metrics():
        raise httpx.ConnectError("refused")

    response = _client(metrics).get("/llama/metrics")
    assert response.status_code == 503
    assert "ConnectError" in response.json()["detail"]
