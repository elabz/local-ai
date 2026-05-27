"""Async Elasticsearch client over the REST API (httpx).

Uses raw REST rather than the version-pinned official client so we are not
coupled to a single ES major version. kNN search uses the 8.x top-level
``knn`` option. Operations: ping, read the vector-field dimension from the
mapping, create the index, upsert a document by id, and kNN-search.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class ESError(RuntimeError):
    """Elasticsearch request failed."""


class ESClient:
    def __init__(self):
        headers = {"Content-Type": "application/json"}
        auth = None
        if settings.es_api_key:
            headers["Authorization"] = f"ApiKey {settings.es_api_key}"
        elif settings.es_username:
            auth = (settings.es_username, settings.es_password)
        self._client = httpx.AsyncClient(
            base_url=settings.es_url.rstrip("/"),
            headers=headers,
            auth=auth,
            timeout=settings.es_timeout,
            verify=settings.es_verify_certs,
        )
        self._index = settings.es_index
        self._field = settings.es_vector_field

    async def aclose(self):
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            resp = await self._client.get("/")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def index_dims(self) -> Optional[int]:
        """Return the configured `dims` of the vector field, or None if the
        index (or field) does not exist yet."""
        resp = await self._client.get(f"/{self._index}/_mapping")
        if resp.status_code == 404:
            return None
        _raise_for_status(resp)
        body = resp.json()
        # { "<index>": { "mappings": { "properties": { "<field>": {...} } } } }
        for idx in body.values():
            props = idx.get("mappings", {}).get("properties", {})
            field = props.get(self._field)
            if field and "dims" in field:
                return field["dims"]
        return None

    async def create_index(self, mapping: Dict[str, Any]) -> None:
        resp = await self._client.put(f"/{self._index}", json=mapping)
        if resp.status_code == 400 and "resource_already_exists" in resp.text:
            return
        _raise_for_status(resp)

    async def upsert(self, doc_id: str, body: Dict[str, Any]) -> None:
        """Idempotent upsert by id (spec: re-ingest overwrites)."""
        resp = await self._client.put(
            f"/{self._index}/_doc/{doc_id}", json=body
        )
        _raise_for_status(resp)

    async def knn_search(
        self,
        vector: List[float],
        k: int,
        num_candidates: int,
        min_score: Optional[float],
        source_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "knn": {
                "field": self._field,
                "query_vector": vector,
                "k": k,
                "num_candidates": max(num_candidates, k),
            },
            "size": k,
            "_source": source_fields if source_fields is not None else True,
        }
        if min_score is not None:
            query["min_score"] = min_score
        resp = await self._client.post(f"/{self._index}/_search", json=query)
        _raise_for_status(resp)
        hits = resp.json().get("hits", {}).get("hits", [])
        return [
            {"id": h.get("_id"), "score": h.get("_score"), "source": h.get("_source", {})}
            for h in hits
        ]


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 300:
        raise ESError(f"Elasticsearch {resp.status_code}: {resp.text[:500]}")
