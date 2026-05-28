"""API routes for the DINOv2 visual-embedding server (image-only, OpenAI-shaped).

DINOv2 has no text encoder, so text inputs are rejected with 400 rather than
returned as meaningless vectors (spec: Image-only — reject text).
"""

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
    input: Union[str, dict, List[Any]]
    model: Optional[str] = None
    encoding_format: Optional[str] = "float"


@router.get("/health")
async def health_check(request: Request):
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None or not embedder.loaded:
        raise HTTPException(status_code=503, detail="Model not ready: loading")
    return {
        "status": "healthy",
        "server_id": settings.server_id,
        "model": settings.model_id,
        "precision": settings.precision,
        "dimension": embedder.dimension,
        "modality": "image-only",
    }


@router.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [
        {"id": settings.model_id.split("/")[-1], "object": "model", "owned_by": "local"}
    ]}


def _encode_vector(vec: List[float], encoding_format: Optional[str]):
    if encoding_format == "base64":
        return base64.b64encode(struct.pack(f"{len(vec)}f", *vec)).decode("ascii")
    return vec


@router.post("/v1/embeddings")
async def create_embeddings(request: Request, body: EmbeddingRequest):
    """Embed image inputs into DINOv2 visual vectors (image-only)."""
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None or not embedder.loaded:
        raise HTTPException(status_code=503, detail="Model not ready")

    inference_requests_total.labels(endpoint="embeddings", status="started").inc()
    active_requests_gauge.inc()
    start_time = time.time()
    try:
        try:
            items: List[InputItem] = await asyncio.to_thread(parse_input, body.input)
        except ImageInputError as e:
            inference_requests_total.labels(endpoint="embeddings", status="bad_request").inc()
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            inference_requests_total.labels(endpoint="embeddings", status="bad_request").inc()
            raise HTTPException(status_code=400, detail=str(e))

        # Image-only: reject any text item (DINOv2 has no text encoder).
        text_idx = [it.index for it in items if it.modality == "text"]
        if text_idx:
            inference_requests_total.labels(endpoint="embeddings", status="bad_request").inc()
            raise HTTPException(
                status_code=400,
                detail=(f"input[{text_idx[0]}] is text; heartcode-embed-visual is "
                        "image-only (DINOv2 has no text encoder). Use an image input."),
            )

        vectors = await asyncio.to_thread(embedder.embed_images, [it.image for it in items])
        data = [
            {"object": "embedding", "index": it.index,
             "embedding": _encode_vector(vec, body.encoding_format)}
            for it, vec in zip(items, vectors)
        ]
        embedding_items_total.labels(modality="image").inc(len(items))
        inference_duration_seconds.labels(endpoint="embeddings").observe(time.time() - start_time)
        inference_requests_total.labels(endpoint="embeddings", status="success").inc()
        return {"object": "list", "data": data,
                "model": settings.model_id.split("/")[-1],
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}
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
