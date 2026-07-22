"""Disposable OpenAI-shaped backend for LiteLLM routing integration tests."""

import os

from fastapi import FastAPI, HTTPException

app = FastAPI()


def available() -> bool:
    return os.getenv("BACKEND_AVAILABLE", "0") == "1"


@app.get("/health")
async def health():
    if not available():
        raise HTTPException(status_code=503, detail={"code": "GPU_UNAVAILABLE", "reason": "gpu_query_failed"})
    return {"status": "healthy"}


@app.get("/v1/models")
async def models():
    if not available():
        raise HTTPException(status_code=503, detail={"code": "GPU_UNAVAILABLE", "reason": "gpu_query_failed"})
    return {"object": "list", "data": [{"id": "test-embed", "object": "model"}]}


@app.post("/v1/embeddings")
async def embeddings():
    if not available():
        raise HTTPException(status_code=503, detail={"code": "GPU_UNAVAILABLE", "reason": "gpu_query_failed"})
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.25, 0.75]}],
        "model": "test-embed",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }
