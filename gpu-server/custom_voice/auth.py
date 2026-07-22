"""HMAC request authentication, replay protection, and bounded rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


class AuthError(ValueError):
    """Safe authentication or authorization failure."""


@dataclass(frozen=True)
class ServiceKey:
    secret: bytes
    scopes: frozenset[str]


class ReplayStore:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS request_nonces(key_id TEXT,nonce TEXT,expires_at INTEGER,PRIMARY KEY(key_id,nonce))")
        path.chmod(0o600)

    def consume(self, key_id: str, nonce: str, expires_at: int, now: int) -> None:
        self.connection.execute("DELETE FROM request_nonces WHERE expires_at < ?", (now,))
        try:
            self.connection.execute("INSERT INTO request_nonces(key_id,nonce,expires_at) VALUES(?,?,?)", (key_id, nonce, expires_at))
        except sqlite3.IntegrityError as error:
            raise AuthError("request_replayed") from error


class RateLimiter:
    def __init__(self, limit: int = 60, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key_id: str, now: float) -> None:
        events = self.events[key_id]
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if len(events) >= self.limit:
            raise AuthError("rate_limit_exceeded")
        events.append(now)


class RequestAuthenticator:
    def __init__(self, keys: dict[str, ServiceKey], replay_store: ReplayStore, *, max_clock_skew_seconds: int = 300, rate_limit: int = 60):
        self.keys = keys
        self.replay_store = replay_store
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.rate_limiter = RateLimiter(rate_limit)

    @staticmethod
    def signature(secret: bytes, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
        body_digest = hashlib.sha256(body).hexdigest()
        message = "\n".join((timestamp, nonce, method.upper(), path, body_digest)).encode()
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def authenticate(self, *, headers, method: str, path: str, body: bytes, required_scope: str, now: int | None = None) -> str:
        key_id = headers.get("x-custom-voice-key-id", "")
        timestamp = headers.get("x-custom-voice-timestamp", "")
        nonce = headers.get("x-custom-voice-nonce", "")
        signature = headers.get("x-custom-voice-signature", "")
        if not KEY_ID_RE.fullmatch(key_id) or not NONCE_RE.fullmatch(nonce) or not SIGNATURE_RE.fullmatch(signature):
            raise AuthError("authentication_failed")
        key = self.keys.get(key_id)
        if key is None:
            raise AuthError("authentication_failed")
        try:
            request_time = int(timestamp)
        except ValueError as error:
            raise AuthError("authentication_failed") from error
        current = int(time.time()) if now is None else now
        if abs(current - request_time) > self.max_clock_skew_seconds:
            raise AuthError("request_timestamp_invalid")
        expected = self.signature(key.secret, timestamp, nonce, method, path, body)
        if not hmac.compare_digest(signature, expected):
            raise AuthError("authentication_failed")
        self.rate_limiter.check(key_id, float(current))
        self.replay_store.consume(key_id, nonce, current + self.max_clock_skew_seconds, current)
        if required_scope not in key.scopes:
            raise AuthError("scope_forbidden")
        return key_id
