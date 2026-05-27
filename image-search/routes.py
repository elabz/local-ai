"""Image-search API routes.

Endpoints:
  POST /ingest        image(s) -> embed -> L2-normalize -> upsert by id   (spec: Image ingestion)
  POST /search/text   text query -> embed -> kNN -> ranked hits           (spec: Text-to-image search)
  POST /search/image  query image -> embed -> kNN -> ranked hits          (spec: Image-to-image search)
  GET  /health        readiness (embed endpoint + ES index dimension)
  GET  /metrics       Prometheus
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import settings
from embed_client import EmbedBadRequest, EmbedError
from metrics import (
    active_requests_gauge,
    items_indexed_total,
    search_duration_seconds,
    search_requests_total,
)
from vectors import DimensionMismatch, check_dim, l2_normalize

logger = logging.getLogger(__name__)
router = APIRouter()

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class IngestItem(BaseModel):
    id: str
    image: str  # data: URI, raw base64, or http(s) URL
    metadata: Optional[Dict[str, Any]] = None
    source_ref: Optional[str] = None  # pointer back to the original asset


class IngestRequest(BaseModel):
    items: Union[IngestItem, List[IngestItem]]


class TextSearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    min_score: Optional[float] = None


class ImageSearchRequest(BaseModel):
    image: str
    top_k: Optional[int] = None
    min_score: Optional[float] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _expected_dim(request: Request) -> int:
    """The dimension queries/docs must match — the live index mapping if known,
    else the configured embed_dim (spec: Shared-space consistency)."""
    return getattr(request.app.state, "index_dims", None) or settings.embed_dim


def _clamp_top_k(top_k: Optional[int]) -> int:
    if top_k is None:
        return settings.default_top_k
    return max(1, min(top_k, settings.max_top_k))


def _ensure_not_oversized(value: str) -> None:
    """Cheap size guard for inline images (no decode). http(s) URLs are left to
    the embedding endpoint's own cap."""
    v = value.strip()
    if _HTTP_URL_RE.match(v):
        return
    b64 = v.split(",", 1)[1] if _DATA_URI_RE.match(v) else v
    approx_bytes = (len(b64) * 3) // 4
    if approx_bytes > settings.max_image_bytes:
        raise HTTPException(status_code=400, detail="image exceeds max_image_bytes")


def _prepare(vec: List[float], request: Request) -> List[float]:
    """Dimension-guard then optionally normalize."""
    try:
        check_dim(vec, _expected_dim(request))
    except DimensionMismatch as e:
        raise HTTPException(status_code=400, detail=str(e))
    return l2_normalize(vec) if settings.normalize else vec


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
@router.post("/ingest")
async def ingest(request: Request, body: IngestRequest):
    items = body.items if isinstance(body.items, list) else [body.items]
    if not items:
        raise HTTPException(status_code=400, detail="'items' must not be empty")
    if len(items) > settings.max_input_items:
        raise HTTPException(
            status_code=400,
            detail=f"{len(items)} items exceeds max_input_items ({settings.max_input_items})",
        )

    embed = request.app.state.embed
    es = request.app.state.es

    search_requests_total.labels(endpoint="ingest", status="started").inc()
    active_requests_gauge.inc()
    start = time.time()

    ingested: List[str] = []
    failed: List[Dict[str, str]] = []
    try:
        # Per-item embed+upsert so one bad image never blocks the rest and never
        # writes a partial document (spec: Embedding failure during ingestion).
        for item in items:
            try:
                _ensure_not_oversized(item.image)
                vec = await embed.embed_image(item.image)
                vec = _prepare(vec, request)
            except HTTPException as e:
                failed.append({"id": item.id, "error": str(e.detail)})
                continue
            except EmbedBadRequest as e:
                failed.append({"id": item.id, "error": f"bad image: {e}"})
                continue
            except EmbedError as e:
                failed.append({"id": item.id, "error": f"embed failed: {e}"})
                continue

            doc = {
                settings.es_id_field: item.id,
                settings.es_vector_field: vec,
                "metadata": item.metadata or {},
                "source_ref": item.source_ref,
                "model": settings.embed_model,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await es.upsert(item.id, doc)
            except Exception as e:
                failed.append({"id": item.id, "error": f"index failed: {e}"})
                continue
            ingested.append(item.id)
            items_indexed_total.inc()

        search_duration_seconds.labels(endpoint="ingest").observe(time.time() - start)
        if ingested:
            search_requests_total.labels(endpoint="ingest", status="success").inc()
        else:
            search_requests_total.labels(endpoint="ingest", status="error").inc()
            # Every item failed -> surface as a 400 with the per-item reasons.
            raise HTTPException(status_code=400, detail={"ingested": [], "failed": failed})

        return {"ingested": ingested, "failed": failed,
                "counts": {"ingested": len(ingested), "failed": len(failed)}}
    finally:
        active_requests_gauge.dec()


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def _hits_response(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "results": [
            {
                "id": h["source"].get(settings.es_id_field, h["id"]),
                "score": h["score"],
                "metadata": h["source"].get("metadata", {}),
                "source_ref": h["source"].get("source_ref"),
            }
            for h in hits
        ],
        "count": len(hits),
    }


async def _run_search(request: Request, vector: List[float], top_k, min_score, endpoint: str):
    es = request.app.state.es
    k = _clamp_top_k(top_k)
    search_requests_total.labels(endpoint=endpoint, status="started").inc()
    active_requests_gauge.inc()
    start = time.time()
    try:
        vec = _prepare(vector, request)
        hits = await es.knn_search(
            vector=vec, k=k, num_candidates=settings.num_candidates,
            min_score=min_score,
            source_fields=[settings.es_id_field, "metadata", "source_ref"],
        )
        search_duration_seconds.labels(endpoint=endpoint).observe(time.time() - start)
        search_requests_total.labels(endpoint=endpoint, status="success").inc()
        return _hits_response(hits)
    finally:
        active_requests_gauge.dec()


@router.post("/search/text")
async def search_text(request: Request, body: TextSearchRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="'query' must not be empty")
    embed = request.app.state.embed
    try:
        vector = await embed.embed_text_query(body.query)
    except EmbedBadRequest as e:
        search_requests_total.labels(endpoint="search_text", status="bad_request").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except EmbedError as e:
        search_requests_total.labels(endpoint="search_text", status="error").inc()
        raise HTTPException(status_code=502, detail=str(e))
    return await _run_search(request, vector, body.top_k, body.min_score, "search_text")


@router.post("/search/image")
async def search_image(request: Request, body: ImageSearchRequest):
    embed = request.app.state.embed
    try:
        _ensure_not_oversized(body.image)
        vector = await embed.embed_image(body.image)
    except EmbedBadRequest as e:
        search_requests_total.labels(endpoint="search_image", status="bad_request").inc()
        raise HTTPException(status_code=400, detail=f"bad image: {e}")
    except EmbedError as e:
        search_requests_total.labels(endpoint="search_image", status="error").inc()
        raise HTTPException(status_code=502, detail=str(e))
    return await _run_search(request, vector, body.top_k, body.min_score, "search_image")


# --------------------------------------------------------------------------- #
# Ops
# --------------------------------------------------------------------------- #
@router.get("/health")
async def health(request: Request):
    es = request.app.state.es
    reachable = await es.ping()
    index_dims = getattr(request.app.state, "index_dims", None)
    ok = reachable and (index_dims is None or index_dims == settings.embed_dim)
    payload = {
        "status": "healthy" if ok else "degraded",
        "server_id": settings.server_id,
        "es_reachable": reachable,
        "index": settings.es_index,
        "index_dims": index_dims,
        "embed_dim": settings.embed_dim,
        "embed_model": settings.embed_model,
    }
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/metrics")
async def get_metrics():
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from fastapi.responses import Response

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
