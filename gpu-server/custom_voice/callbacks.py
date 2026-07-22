"""Allow-listed, signed, best-effort custom-voice callbacks."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Callable


class CallbackError(ValueError):
    """Safe callback configuration or delivery failure."""


@dataclass(frozen=True)
class CallbackTarget:
    url: str
    secret: bytes


class CallbackDispatcher:
    def __init__(
        self,
        targets: dict[str, CallbackTarget],
        post: Callable[..., object],
        *,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.targets = targets
        self.post = post
        self.attempts = attempts
        self.sleep = sleep

    @staticmethod
    def signature(secret: bytes, timestamp: str, nonce: str, body: bytes) -> str:
        message = b"\n".join((timestamp.encode(), nonce.encode(), hashlib.sha256(body).hexdigest().encode()))
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def deliver(self, callback_id: str, event: dict[str, object]) -> dict[str, object]:
        target = self.targets.get(callback_id)
        if target is None:
            raise CallbackError("callback_target_unknown")
        allowed_keys = {"schema_version", "callback_id", "event_id", "job_id", "state", "occurred_at", "reason"}
        if set(event) - allowed_keys or event.get("schema_version") != "custom-voice-callback.v1" or event.get("callback_id") != callback_id:
            raise CallbackError("callback_event_invalid")
        body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        last_status = 0
        for attempt in range(self.attempts):
            timestamp = str(int(time.time()))
            nonce = secrets.token_urlsafe(18)
            headers = {
                "Content-Type": "application/json",
                "X-Custom-Voice-Timestamp": timestamp,
                "X-Custom-Voice-Nonce": nonce,
                "X-Custom-Voice-Signature": self.signature(target.secret, timestamp, nonce, body),
            }
            try:
                response = self.post(target.url, content=body, headers=headers, timeout=10, follow_redirects=False)
                last_status = int(response.status_code)
                if 200 <= last_status < 300:
                    return {"outcome": "delivered", "attempts": attempt + 1, "status": last_status}
                if 400 <= last_status < 500 and last_status != 429:
                    break
            except OSError:
                last_status = 0
            if attempt + 1 < self.attempts:
                self.sleep(min(2 ** attempt, 8))
        return {"outcome": "failed", "attempts": min(self.attempts, attempt + 1), "status": last_status}
