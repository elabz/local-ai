"""Bound what HeartCode's public API keys can ask of the shared chat fleet.

HeartCode mints LiteLLM virtual keys for third-party clients (SillyTavern),
which call this proxy directly. Those requests share the Pea chat slots with
HeartCode's own chat: three SFW and two NSFW llama.cpp slots, one generation
each. Per-key `rpm`/`tpm`/`max_parallel_requests` bound a single key; nothing
bounded the public keys together, and team-level `max_parallel_requests` is
not enforced by LiteLLM 1.81.9 (measured 2026-10-10: three concurrent
requests on a team capped at 1 all succeeded). So this callback does it.

A key is public when its metadata carries `heartcode_key_name`, which
HeartCode's key creation sets and its own backend key does not. Everything
else passes through untouched. For public chat requests it:

- rejects more than `PUBLIC_API_MAX_MESSAGES` messages, or any message whose
  content exceeds `PUBLIC_API_MAX_MESSAGE_BYTES` (HTTP 413);
- clamps sampler values and `max_tokens` into `SAMPLER_BOUNDS`, and rejects a
  non-numeric one (HTTP 400);
- admits at most `PUBLIC_API_PARALLEL` public generations per model group at
  once, answering the next with 429 and `Retry-After`, so first-party chat
  keeps the remaining slots.

Admission is in-process, which is exact while the proxy runs one worker (it
does: no `--num_workers`). A slot is released when the request succeeds,
fails, or its stream ends or is abandoned; one never released (a path that
skips every hook) expires after `STALE_AFTER_SECONDS`.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

try:  # The proxy image has litellm; the unit tests do not need it.
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # pragma: no cover - exercised only outside the image
    CustomLogger = object  # type: ignore[assignment,misc]

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover

    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: Any = None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers


PUBLIC_KEY_MARKER = "heartcode_key_name"
CHAT_CALL_TYPES = frozenset({"completion", "acompletion", "text_completion", "atext_completion"})

# Mirrors `router_settings.model_group_alias` in config.base.yaml; a test
# holds the two together. Admission counts per real model group, so an alias
# cannot be used to take a second slot.
MODEL_GROUP_ALIASES = {
    "heartcode-default": "heartcode-chat-sfw",
    "heartcode-sfw": "heartcode-chat-sfw",
    "heartcode-chat": "heartcode-chat-sfw",
    "heartcode-nsfw": "heartcode-chat-nsfw",
}

# (low, high) per field. Values outside are clamped, not refused: clients such
# as SillyTavern ship presets that overshoot, and a clamped request is more
# useful to the user than an error. llama.cpp reads top_k 0 as "off".
SAMPLER_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "top_k": (0, 200),
    "min_p": (0.0, 1.0),
    "repetition_penalty": (0.5, 2.0),
    "repeat_penalty": (0.5, 2.0),
    "presence_penalty": (-2.0, 2.0),
    "frequency_penalty": (-2.0, 2.0),
}
INTEGER_FIELDS = frozenset({"top_k", "max_tokens", "max_completion_tokens"})

STALE_AFTER_SECONDS = 300.0  # above the proxy's 240 s request timeout
RETRY_AFTER_SECONDS = 5


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _parallel_from_env(raw: str | None) -> dict[str, int]:
    """`heartcode-chat-sfw=1,heartcode-chat-nsfw=1` → dict. Unlisted groups get
    `default`."""
    limits: dict[str, int] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            name, value = part.split("=", 1)
            try:
                limits[name.strip()] = int(value)
            except ValueError:
                continue
    return limits


def is_public_key(user_api_key_dict: Any) -> bool:
    metadata = getattr(user_api_key_dict, "metadata", None) or {}
    return isinstance(metadata, dict) and PUBLIC_KEY_MARKER in metadata


def model_group(requested: str | None) -> str:
    name = requested or ""
    return MODEL_GROUP_ALIASES.get(name, name)


def _content_bytes(content: Any) -> int:
    """Size of a message's text: a string, or the text parts of a list."""
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        return sum(
            len(str(part.get("text", "")).encode("utf-8"))
            for part in content
            if isinstance(part, dict)
        )
    return 0


def check_messages(data: dict[str, Any], max_messages: int, max_bytes: int) -> None:
    messages = data.get("messages")
    if messages is None:
        prompt = data.get("prompt")
        if isinstance(prompt, str) and len(prompt.encode("utf-8")) > max_bytes:
            raise HTTPException(413, f"prompt exceeds {max_bytes} bytes")
        return
    if not isinstance(messages, list):
        raise HTTPException(400, "messages must be a list")
    if len(messages) > max_messages:
        raise HTTPException(413, f"at most {max_messages} messages per request")
    for index, message in enumerate(messages):
        content = message.get("content") if isinstance(message, dict) else None
        if _content_bytes(content) > max_bytes:
            raise HTTPException(413, f"message {index} exceeds {max_bytes} bytes")


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(400, f"{name} must be a number")
    if not math.isfinite(value):
        raise HTTPException(400, f"{name} must be finite")
    return float(value)


def clamp_samplers(data: dict[str, Any], max_tokens_ceiling: int) -> None:
    """Clamp in place. Absent fields stay absent."""
    bounds = {
        **SAMPLER_BOUNDS,
        "max_tokens": (1, max_tokens_ceiling),
        "max_completion_tokens": (1, max_tokens_ceiling),
    }
    for name, (low, high) in bounds.items():
        if data.get(name) is None:
            continue
        value = min(max(_number(name, data[name]), low), high)
        data[name] = int(value) if name in INTEGER_FIELDS else value
    # A ceiling is only a ceiling if it applies when the client sends nothing.
    if data.get("max_tokens") is None and data.get("max_completion_tokens") is None:
        data["max_tokens"] = max_tokens_ceiling
    # One choice per request: `n` multiplies the work a request may do.
    if data.get("n") is not None:
        data["n"] = 1


class AdmissionGate:
    """Public generations in flight, per model group."""

    def __init__(self, limits: dict[str, int], default_limit: int):
        self.limits = limits
        self.default_limit = default_limit
        self._in_flight: dict[str, tuple[str, float]] = {}  # id → (group, started)

    def _prune(self, now: float) -> None:
        stale = [
            request_id
            for request_id, (_, started) in self._in_flight.items()
            if now - started > STALE_AFTER_SECONDS
        ]
        for request_id in stale:
            self._in_flight.pop(request_id, None)

    def in_flight(self, group: str) -> int:
        return sum(1 for g, _ in self._in_flight.values() if g == group)

    def acquire(self, request_id: str, group: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(now)
        limit = self.limits.get(group, self.default_limit)
        if self.in_flight(group) >= limit:
            raise HTTPException(
                429,
                "Public API capacity for this model is in use. Retry shortly.",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        self._in_flight[request_id] = (group, now)

    def release(self, request_id: str | None) -> None:
        if request_id:
            self._in_flight.pop(request_id, None)


def _request_id(data: dict[str, Any]) -> str | None:
    return data.get("litellm_call_id") or data.get("_public_api_guard_id")


class PublicApiGuard(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self.max_messages = _int_env("PUBLIC_API_MAX_MESSAGES", 100)
        self.max_message_bytes = _int_env("PUBLIC_API_MAX_MESSAGE_BYTES", 32 * 1024)
        self.max_tokens = _int_env("PUBLIC_API_MAX_TOKENS", 1024)
        self.gate = AdmissionGate(
            _parallel_from_env(os.environ.get("PUBLIC_API_PARALLEL")),
            _int_env("PUBLIC_API_PARALLEL_DEFAULT", 1),
        )

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type not in CHAT_CALL_TYPES or not is_public_key(user_api_key_dict):
            return data
        check_messages(data, self.max_messages, self.max_message_bytes)
        clamp_samplers(data, self.max_tokens)
        if not data.get("litellm_call_id"):
            data["_public_api_guard_id"] = f"guard-{id(data)}-{time.monotonic_ns()}"
        self.gate.acquire(_request_id(data), model_group(data.get("model")))
        data["_public_api_guard_admitted"] = True
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        # A stream's success fires before its body is sent; its slot is held
        # until the iterator below finishes.
        if data.get("_public_api_guard_admitted") and not data.get("stream"):
            self.gate.release(_request_id(data))
        return response

    async def async_post_call_failure_hook(
        self, request_data, original_exception, user_api_key_dict, traceback_str=None
    ):
        if request_data.get("_public_api_guard_admitted"):
            self.gate.release(_request_id(request_data))

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data
    ) -> AsyncGenerator[Any, None]:
        try:
            async for chunk in response:
                yield chunk
        finally:
            if request_data.get("_public_api_guard_admitted"):
                self.gate.release(_request_id(request_data))


public_api_guard = PublicApiGuard()
