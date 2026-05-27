"""API routes for the multimodal embedding server (OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
import time
from typing import Any, List, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import settings
from image_input import ImageInputError, InputItem, parse_input
from metrics import (
    active_requests_gauge,
    embedding_items_total,
    inference_duration_seconds,
    inference_requests_total,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class EmbeddingRequest(BaseModel):
    # input: str | list[str] | dict | list[str|dict] (see image_input.parse_input)
    input: Union[str, dict, List[Any]]
    model: Optional[str] = None  # accepted for OpenAI compatibility, ignored
    encoding_format: Optional[str] = "float"  # "float" | "base64"


@router.get("/health")
async def health_check(request: Request):
    """503 until the model is loaded and can serve an embedding."""
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None or not embedder.loaded:
        raise HTTPException(status_code=503, detail="Model not ready: loading")
    return {
        "status": "healthy",
        "server_id": settings.server_id,
        "model": settings.model_id,
        "precision": settings.precision,
        "dimension": embedder.dimension,
    }


@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": settings.model_id.split("/")[-1],
                "object": "model",
                "owned_by": "local",
            }
        ],
    }


def _encode_vector(vec: List[float], encoding_format: Optional[str]):
    if encoding_format == "base64":
        packed = struct.pack(f"{len(vec)}f", *vec)
        return base64.b64encode(packed).decode("ascii")
    return vec


@router.post("/v1/embeddings")
async def create_embeddings(request: Request, body: EmbeddingRequest):
    """Embed text and/or image inputs into one shared vector space.

    Returns OpenAI ``data[]`` shape with one vector per input item, in input
    order. Malformed image items -> 400 identifying the offending index.
    """
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None or not embedder.loaded:
        raise HTTPException(status_code=503, detail="Model not ready")

    inference_requests_total.labels(endpoint="embeddings", status="started").inc()
    active_requests_gauge.inc()
    start_time = time.time()

    try:
        # Parse + classify (runs decode/fetch off the event loop).
        try:
            items: List[InputItem] = await asyncio.to_thread(parse_input, body.input)
        except ImageInputError as e:
            inference_requests_total.labels(endpoint="embeddings", status="bad_request").inc()
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            inference_requests_total.labels(endpoint="embeddings", status="bad_request").inc()
            raise HTTPException(status_code=400, detail=str(e))

        text_items = [it for it in items if it.modality == "text"]
        image_items = [it for it in items if it.modality == "image"]

        # Run the two branches in worker threads (GPU work is serialized inside
        # the embedder via its lock).
        text_vecs, image_vecs = await asyncio.gather(
            asyncio.to_thread(embedder.embed_texts, [it.text for it in text_items]),
            asyncio.to_thread(embedder.embed_images, [it.image for it in image_items]),
        )

        # Reassemble in original input order.
        ordered: List[Optional[List[float]]] = [None] * len(items)
        for it, vec in zip(text_items, text_vecs):
            ordered[it.index] = vec
        for it, vec in zip(image_items, image_vecs):
            ordered[it.index] = vec

        if any(vec is None for vec in ordered):
            raise RuntimeError("internal error: an input item produced no vector")

        data = [
            {
                "object": "embedding",
                "index": idx,
                "embedding": _encode_vector(vec, body.encoding_format),
            }
            for idx, vec in enumerate(ordered)
            if vec is not None
        ]

        embedding_items_total.labels(modality="text").inc(len(text_items))
        embedding_items_total.labels(modality="image").inc(len(image_items))

        duration = time.time() - start_time
        inference_duration_seconds.labels(endpoint="embeddings").observe(duration)
        inference_requests_total.labels(endpoint="embeddings", status="success").inc()

        return {
            "object": "list",
            "data": data,
            "model": settings.model_id.split("/")[-1],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    except HTTPException:
        raise
    except Exception as e:
        inference_requests_total.labels(endpoint="embeddings", status="error").inc()
        logger.error(f"Embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        active_requests_gauge.dec()


@router.get("/metrics")
async def get_metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
