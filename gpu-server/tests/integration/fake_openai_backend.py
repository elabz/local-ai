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

In any mode, POST /fail?n=N makes the next N probe requests (chat,
transcription or speech) answer a plain 500, the way a speech server does when
it errors on one request while staying up; /health keeps answering 200.

A chat request whose body contains the marker "routing-probe" is a test probe;
anything else (LiteLLM's background health check also issues chat calls for
`mode: chat` deployments) is counted separately so the assertions only see
traffic the test itself sent. GET /stats reports per-path status counts so a
test can prove that LiteLLM kept (or stopped) sending traffic to this backend.

BACKEND_NAME (default: the mode) is what a chat reply says served it, so a
test can tell replicas apart. A streamed chat request gets an SSE answer, with
a final usage chunk carrying `prompt_tokens_details.cached_tokens` when the
request asked for `stream_options.include_usage`, as llama-server sends it.
GET /last-chat returns the last probe chat body this backend received.
"""

import json
import os
import threading
from collections import Counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

app = FastAPI()

MODE = os.getenv("BACKEND_MODE") or ("healthy" if os.getenv("BACKEND_AVAILABLE", "0") == "1" else "unavailable")
NAME = os.getenv("BACKEND_NAME") or MODE
CACHED_TOKENS = 7
_last_chat: dict = {}
_lock = threading.Lock()
_stats: Counter = Counter()
_chat_calls = 0
_fail_remaining = 0


def available() -> bool:
    return MODE != "unavailable"


def _count(path: str, status: int) -> None:
    with _lock:
        _stats[f"{path} {status}"] += 1


def _take_injected_failure(path: str) -> JSONResponse | None:
    global _fail_remaining
    with _lock:
        if _fail_remaining <= 0:
            return None
        _fail_remaining -= 1
    _count(path, 500)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "injected failure", "type": "server_error", "code": "INTERNAL_ERROR"}},
    )


@app.post("/fail")
async def fail(n: int):
    global _fail_remaining
    with _lock:
        _fail_remaining = n
    return {"fail_remaining": n}


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


@app.get("/last-chat")
async def last_chat():
    with _lock:
        return dict(_last_chat)


def _sse(payload: dict, include_usage: bool):
    def chunk(data) -> str:
        return f"data: {json.dumps(data)}\n\n"

    base = {"id": f"chatcmpl-{NAME}", "object": "chat.completion.chunk", "model": "test-chat"}
    yield chunk({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": f"served-by-{NAME}"}, "finish_reason": None}]})
    yield chunk({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if include_usage:
        yield chunk({**base, "choices": [], "usage": {
            "prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": CACHED_TOKENS}}})
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    global _chat_calls
    payload = await request.json()
    body = json.dumps(payload)
    probe = "routing-probe" in body
    if probe:
        with _lock:
            _last_chat.clear()
            _last_chat.update(payload)
    path = "/v1/chat/completions" + (" probe" if probe else " other")
    if not available():
        raise _unavailable(path)
    if probe and (injected := _take_injected_failure(path)):
        return injected
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
    if payload.get("stream"):
        include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
        return StreamingResponse(_sse(payload, include_usage), media_type="text/event-stream")
    return {
        "id": f"chatcmpl-{NAME}",
        "object": "chat.completion",
        "model": "test-chat",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": f"served-by-{NAME}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                  "prompt_tokens_details": {"cached_tokens": CACHED_TOKENS}},
    }


@app.post("/v1/audio/transcriptions")
async def transcriptions(request: Request):
    # Read the multipart body raw: the uploaded "audio" of a probe carries the marker.
    probe = b"routing-probe" in await request.body()
    path = "/v1/audio/transcriptions" + (" probe" if probe else " other")
    if not available():
        raise _unavailable(path)
    if probe and (injected := _take_injected_failure(path)):
        return injected
    _count(path, 200)
    return {"text": f"served-by-{MODE}"}


@app.post("/v1/audio/speech")
async def speech(request: Request):
    probe = b"routing-probe" in await request.body()
    path = "/v1/audio/speech" + (" probe" if probe else " other")
    if not available():
        raise _unavailable(path)
    if probe and (injected := _take_injected_failure(path)):
        return injected
    _count(path, 200)
    return Response(content=b"OggS-fake-audio", media_type="audio/ogg")
