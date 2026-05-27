"""Async client for the heartcode-embed OpenAI-compatible /v1/embeddings API.

The service is model-agnostic: text items are sent as plain strings (the
configured `text_query_prefix` is prepended to text *queries* by the caller),
image items as ``{"image": <data-uri|base64|url>}`` — the documented
heartcode-embed input convention. Upstream 4xx (e.g. a malformed image) is
surfaced as ``EmbedBadRequest`` so routes can return 400 without crashing
(spec: Image-to-image search).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

import httpx

from config import settings

logger = logging.getLogger(__name__)

EmbedItem = Union[str, Dict[str, Any]]


class EmbedBadRequest(ValueError):
    """Upstream embedding endpoint rejected the input (HTTP 4xx)."""


class EmbedError(RuntimeError):
    """Upstream embedding endpoint failed (network/5xx/timeout)."""


class EmbedClient:
    def __init__(self):
        headers = {"Content-Type": "application/json"}
        if settings.embed_api_key:
            headers["Authorization"] = f"Bearer {settings.embed_api_key}"
        self._client = httpx.AsyncClient(
            base_url=settings.embed_base_url.rstrip("/"),
            headers=headers,
            timeout=settings.embed_timeout,
        )

    async def aclose(self):
        await self._client.aclose()

    async def embed(self, items: List[EmbedItem]) -> List[List[float]]:
        """Embed a batch of text/image items, returning vectors in input order."""
        if not items:
            return []
        try:
            resp = await self._client.post(
                "/embeddings", json={"model": settings.embed_model, "input": items}
            )
        except httpx.HTTPError as e:
            raise EmbedError(f"embedding endpoint unreachable: {e}") from e

        if resp.status_code == 400 or resp.status_code == 422:
            raise EmbedBadRequest(_detail(resp))
        if resp.status_code >= 500 or resp.status_code in (401, 403, 404, 429):
            raise EmbedError(f"embedding endpoint error {resp.status_code}: {_detail(resp)}")

        data = resp.json().get("data", [])
        # Order by the returned index to be safe, then strip to vectors.
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    async def embed_text_query(self, text: str) -> List[float]:
        prefixed = f"{settings.text_query_prefix}{text}"
        return (await self.embed([prefixed]))[0]

    async def embed_image(self, value: str) -> List[float]:
        return (await self.embed([{"image": value}]))[0]


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("detail") or body.get("error") or body)
    except Exception:
        return resp.text[:500]
