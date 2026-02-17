"""API routes for GPU server."""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from config import settings
from metrics import (
    inference_requests_total,
    inference_duration_seconds,
    inference_tokens_total,
    active_requests_gauge,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response models
class Message(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = Field(default=None, alias="max_tokens")
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    repeat_penalty: Optional[float] = None
    stop: Optional[List[str]] = None
    stream: bool = False


class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: bool = False
    model: Optional[str] = None  # Ignored, for OpenAI compatibility


class TokenizeRequest(BaseModel):
    content: str


# Routes
@router.get("/health")
async def health_check(request: Request):
    """Health check endpoint. Returns 503 unless llama.cpp reports status 'ok'."""
    try:
        llama_client = request.app.state.llama_client
        health = await llama_client.health_check()
        llama_status = health.get("status")

        if llama_status != "ok":
            logger.warning(
                f"Health check: llama.cpp status is '{llama_status}', not 'ok'"
            )
            raise HTTPException(
                status_code=503,
                detail=f"Model not ready: {llama_status}",
            )

        return {
            "status": "healthy",
            "server_id": settings.server_id,
            "llama_status": llama_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Server unhealthy")


@router.get("/v1/models")
async def list_models():
    """List available models (OpenAI compatible)."""
    model_name = settings.model_path.split("/")[-1]
    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "owned_by": "local",
            }
        ],
    }


@router.post("/v1/completions")
async def create_completion(request: Request, body: CompletionRequest):
    """Create completion (OpenAI compatible)."""
    llama_client = request.app.state.llama_client

    inference_requests_total.labels(endpoint="completions", status="started").inc()
    active_requests_gauge.inc()
    start_time = time.time()

    try:
        if body.stream:
            return EventSourceResponse(
                _stream_completion(llama_client, body),
                media_type="text/event-stream",
            )

        result = await llama_client.completion(
            prompt=body.prompt,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            top_k=body.top_k,
            repeat_penalty=body.repeat_penalty,
            stop=body.stop,
        )

        duration = time.time() - start_time
        inference_duration_seconds.labels(endpoint="completions").observe(duration)
        inference_requests_total.labels(endpoint="completions", status="success").inc()
        inference_tokens_total.labels(type="completion").inc(
            result.get("tokens_predicted", 0)
        )

        return {
            "id": f"cmpl-{settings.server_id}-{int(time.time())}",
            "object": "text_completion",
            "model": settings.model_path.split("/")[-1],
            "choices": [
                {
                    "text": result.get("content", ""),
                    "index": 0,
                    "finish_reason": "stop" if result.get("stop") else "length",
                }
            ],
            "usage": {
                "prompt_tokens": result.get("tokens_evaluated", 0),
                "completion_tokens": result.get("tokens_predicted", 0),
                "total_tokens": result.get("tokens_evaluated", 0)
                + result.get("tokens_predicted", 0),
            },
        }

    except Exception as e:
        inference_requests_total.labels(endpoint="completions", status="error").inc()
        logger.error(f"Completion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        active_requests_gauge.dec()


@router.post("/v1/chat/completions")
async def create_chat_completion(request: Request, body: ChatCompletionRequest):
    """Create chat completion (OpenAI compatible)."""
    llama_client = request.app.state.llama_client

    inference_requests_total.labels(endpoint="chat", status="started").inc()
    active_requests_gauge.inc()
    start_time = time.time()

    try:
        messages = [{"role": m.role, "content": m.content} for m in body.messages]

        if body.stream:
            return EventSourceResponse(
                _stream_chat_completion(llama_client, messages, body),
                media_type="text/event-stream",
            )

        result = await llama_client.chat_completion(
            messages=messages,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            stream=False,
        )

        duration = time.time() - start_time
        inference_duration_seconds.labels(endpoint="chat").observe(duration)
        inference_requests_total.labels(endpoint="chat", status="success").inc()
        inference_tokens_total.labels(type="completion").inc(
            result.get("usage", {}).get("completion_tokens", 0)
        )

        return result

    except Exception as e:
        inference_requests_total.labels(endpoint="chat", status="error").inc()
        logger.error(f"Chat completion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        active_requests_gauge.dec()


async def _stream_completion(llama_client, body: CompletionRequest):
    """Stream completion responses."""
    try:
        async for token in llama_client.completion_stream(
            prompt=body.prompt,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            top_k=body.top_k,
            repeat_penalty=body.repeat_penalty,
            stop=body.stop,
        ):
            yield {
                "data": {
                    "id": f"cmpl-{settings.server_id}",
                    "object": "text_completion",
                    "choices": [{"text": token, "index": 0}],
                }
            }
        yield {"data": "[DONE]"}
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield {"data": {"error": str(e)}}


async def _stream_chat_completion(llama_client, messages: list, body: ChatCompletionRequest):
    """Stream chat completion responses via llama.cpp native chat API."""
    import orjson

    try:
        async for token in llama_client.chat_completion_stream(
            messages=messages,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
        ):
            chunk = {
                "id": f"chatcmpl-{settings.server_id}",
                "object": "chat.completion.chunk",
                "model": settings.model_path.split("/")[-1],
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None,
                    }
                ],
            }
            yield {"data": orjson.dumps(chunk).decode()}

        # Send final chunk
        final_chunk = {
            "id": f"chatcmpl-{settings.server_id}",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield {"data": orjson.dumps(final_chunk).decode()}
        yield {"data": "[DONE]"}

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield {"data": orjson.dumps({"error": str(e)}).decode()}


@router.post("/tokenize")
async def tokenize(request: Request, body: TokenizeRequest):
    """Tokenize text."""
    llama_client = request.app.state.llama_client
    result = await llama_client.tokenize(body.content)
    return result


@router.get("/metrics")
async def get_metrics():
    """Get Prometheus metrics."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
