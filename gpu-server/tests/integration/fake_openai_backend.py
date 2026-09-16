"""Disposable OpenAI-shaped backend for LiteLLM routing integration tests.

BACKEND_MODE selects the personality (BACKEND_AVAILABLE=0/1 is still honoured
for the older embedding scenarios):

  healthy      serves everything
  unavailable  503 GPU_UNAVAILABLE everywhere (mirrors a wrapper whose GPU is gone)
  busy         /health is 200 (a busy wrapper is alive) but every chat request
               answers 429 BACKEND_BUSY + Retry-After, mirroring the wrapper's
               bounded admission queue overflowing
  flaky        the first *probe* chat request answers 503 BACKEND_UNAVAILABLE,
               every later one succeeds (a single transient downstream timeout)

A chat request whose body contains the marker "routing-probe" is a test probe;
anything else (LiteLLM's background health check also issues chat calls for
`mode: chat` deployments) is counted separately so the assertions only see
traffic the test itself sent. GET /stats reports per-path status counts so a
test can prove that LiteLLM kept (or stopped) sending traffic to this backend.
"""

import json
import os
import threading
from collections import Counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

MODE = os.getenv("BACKEND_MODE") or ("healthy" if os.getenv("BACKEND_AVAILABLE", "0") == "1" else "unavailable")
_lock = threading.Lock()
_stats: Counter = Counter()
_chat_calls = 0


def available() -> bool:
    return MODE != "unavailable"


def _count(path: str, status: int) -> None:
    with _lock:
        _stats[f"{path} {status}"] += 1


def _unavailable(path: str) -> HTTPException:
    _count(path, 503)
    return HTTPException(status_code=503, detail={"code": "GPU_UNAVAILABLE", "reason": "gpu_query_failed"})


@app.get("/stats")
async def stats():
    with _lock:
        return {"mode": MODE, "counts": dict(_stats)}


@app.get("/health")
async def health():
    if not available():
        raise _unavailable("/health")
    _count("/health", 200)
    return {"status": "healthy", "backend_state": "busy" if MODE == "busy" else "ready"}


@app.get("/v1/models")
async def models():
    if not available():
        raise _unavailable("/v1/models")
    _count("/v1/models", 200)
    return {"object": "list", "data": [{"id": "test-embed", "object": "model"}, {"id": "test-chat", "object": "model"}]}


@app.post("/v1/embeddings")
async def embeddings():
    if not available():
        raise _unavailable("/v1/embeddings")
    _count("/v1/embeddings", 200)
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.25, 0.75]}],
        "model": "test-embed",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    global _chat_calls
    body = json.dumps(await request.json())
    probe = "routing-probe" in body
    path = "/v1/chat/completions" + (" probe" if probe else " other")
    if not available():
        raise _unavailable(path)
    call_index = 0
    if probe:
        with _lock:
            _chat_calls += 1
            call_index = _chat_calls
    if MODE == "busy":
        _count(path, 429)
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            content={"error": {"message": "backend busy", "type": "server_error", "code": "BACKEND_BUSY"},
                     "detail": {"code": "BACKEND_BUSY", "reason": "capacity_exhausted"}},
        )
    if MODE == "flaky" and probe and call_index == 1:
        _count(path, 503)
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "downstream timeout", "type": "server_error", "code": "BACKEND_UNAVAILABLE"},
                     "detail": {"code": "BACKEND_UNAVAILABLE", "reason": "downstream_timeout"}},
        )
    _count(path, 200)
    return {
        "id": f"chatcmpl-{MODE}",
        "object": "chat.completion",
        "model": "test-chat",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": f"served-by-{MODE}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
