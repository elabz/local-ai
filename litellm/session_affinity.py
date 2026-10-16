"""Carry a request's session id to the least-busy tie-break (serve-prompt-cache-reuse).

The Pea chat workers keep the previous turn's prompt in their llama.cpp cache,
so a conversation's next turn is ~4x cheaper to start on the same replica.
LiteLLM's least-busy strategy never sees the request, and the local patch
breaks idle ties at random, so one conversation's turns used to scatter.

LiteLLM runs every callback's `async_filter_deployments` with the request's
kwargs before the strategy picks, inside the same awaited routing call. This
filter reads the session id and leaves it in `session_affinity_id`, which the
patched `least_busy.py` reads to break ties by rendezvous hashing. It never
removes a deployment, so cooldowns, health and least-busy are unchanged.

The id is taken from, in order:
- the `X-Session-Id` request header (`metadata["headers"]`);
- `metadata["session_id"]` in the request body.

It is opaque, used only for hashing, and never logged.
"""
from __future__ import annotations

from typing import Any, Optional

try:  # The proxy image has litellm; the unit tests stub it.
    from litellm.integrations.custom_logger import CustomLogger
    from litellm.router_strategy.least_busy import session_affinity_id
except ImportError:  # pragma: no cover - exercised only outside the image
    from contextvars import ContextVar

    CustomLogger = object  # type: ignore[assignment,misc]
    session_affinity_id: ContextVar[Optional[str]] = ContextVar(
        "heartcode_session_affinity_id", default=None
    )

HEADER = "x-session-id"
METADATA_KEY = "session_id"
MAX_LENGTH = 128


def session_id_from(request_kwargs: Optional[dict]) -> Optional[str]:
    """The request's session id, or None. Bounded and stripped."""
    if not isinstance(request_kwargs, dict):
        return None
    for metadata_key in ("metadata", "litellm_metadata"):
        metadata = request_kwargs.get(metadata_key)
        if not isinstance(metadata, dict):
            continue
        headers = metadata.get("headers")
        if isinstance(headers, dict):
            for name, value in headers.items():
                if isinstance(name, str) and name.lower() == HEADER:
                    found = _clean(value)
                    if found:
                        return found
        found = _clean(metadata.get(METADATA_KEY))
        if found:
            return found
    return None


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_LENGTH:
        return None
    return value


class SessionAffinity(CustomLogger):  # type: ignore[misc,valid-type]
    async def async_filter_deployments(
        self,
        model: str,
        healthy_deployments: list,
        messages: Optional[list] = None,
        request_kwargs: Optional[dict] = None,
        parent_otel_span: Any = None,
    ) -> list:
        # Set on every routing call, so a value never outlives its request.
        session_affinity_id.set(session_id_from(request_kwargs))
        return healthy_deployments


session_affinity = SessionAffinity()
