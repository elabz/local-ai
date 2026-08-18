"""Bounded, content-free availability state for llama.cpp backends."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional


STATES = {"starting", "ready", "busy", "degraded", "unavailable"}
REASONS = {
    "starting", "ready", "inference_active", "busy_probe_timeout",
    "idle_probe_failure", "stuck_request", "child_exit", "gpu_unavailable",
    "restart_suppressed", "recovering",
}


@dataclass(frozen=True)
class AvailabilitySnapshot:
    state: str
    reason: str
    in_flight: int
    probe_failures: int
    oldest_request_seconds: float


@dataclass(frozen=True)
class WatchdogDecision:
    restart: bool
    reason: str


class BackendAvailability:
    """Track occupancy and make restart decisions without request identifiers."""

    def __init__(
        self,
        *,
        idle_failure_limit: int = 3,
        stuck_request_seconds: float = 300.0,
        restart_limit: int = 3,
        restart_window_seconds: float = 900.0,
        restart_state_path: Optional[str] = None,
        on_transition: Optional[Callable[[str, str], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.idle_failure_limit = max(1, idle_failure_limit)
        self.stuck_request_seconds = max(1.0, stuck_request_seconds)
        self.restart_limit = max(1, restart_limit)
        self.restart_window_seconds = max(1.0, restart_window_seconds)
        self.restart_state_path = Path(restart_state_path) if restart_state_path else None
        self.on_transition = on_transition
        self.clock = clock
        self.wall_clock = wall_clock
        self._lock = threading.Lock()
        self._started: Deque[float] = deque()
        self._last_progress = self.clock()
        self._probe_failures = 0
        self._state = "starting"
        self._reason = "starting"

    def _transition(self, state: str, reason: str) -> None:
        state = state if state in STATES else "unavailable"
        reason = reason if reason in REASONS else "idle_probe_failure"
        changed = (state, reason) != (self._state, self._reason)
        self._state, self._reason = state, reason
        if changed and self.on_transition:
            self.on_transition(state, reason)

    def begin_request(self) -> None:
        with self._lock:
            self._started.append(self.clock())
            self._transition("busy", "inference_active")

    def end_request(self) -> None:
        with self._lock:
            if self._started:
                self._started.popleft()
                self._last_progress = self.clock()
            if not self._started and self._state == "busy":
                # A completed inference is stronger liveness evidence than a
                # delayed concurrent HTTP probe.
                self._probe_failures = 0
                self._transition("ready", "ready")

    def probe_succeeded(self) -> None:
        with self._lock:
            self._probe_failures = 0
            self._transition(
                "busy" if self._started else "ready",
                "inference_active" if self._started else "ready",
            )

    def probe_failed(self, *, child_alive: bool = True) -> WatchdogDecision:
        with self._lock:
            self._probe_failures += 1
            if not child_alive:
                self._transition("unavailable", "child_exit")
                return self._restart_decision("child_exit")

            oldest = self._oldest_seconds()
            progress_age = max(0.0, self.clock() - self._last_progress)
            if self._started and (
                oldest < self.stuck_request_seconds or progress_age < self.stuck_request_seconds
            ):
                self._transition("busy", "busy_probe_timeout")
                return WatchdogDecision(False, "busy_probe_timeout")

            reason = "stuck_request" if self._started else "idle_probe_failure"
            self._transition("degraded", reason)
            if self._probe_failures < self.idle_failure_limit:
                return WatchdogDecision(False, reason)
            return self._restart_decision(reason)

    def child_exited(self) -> WatchdogDecision:
        with self._lock:
            self._transition("unavailable", "child_exit")
            return self._restart_decision("child_exit")

    def mark_unavailable(self, reason: str = "gpu_unavailable") -> None:
        with self._lock:
            self._transition("unavailable", reason)

    def snapshot(self) -> AvailabilitySnapshot:
        with self._lock:
            return AvailabilitySnapshot(
                self._state, self._reason, len(self._started),
                self._probe_failures, self._oldest_seconds(),
            )

    def _oldest_seconds(self) -> float:
        return max(0.0, self.clock() - self._started[0]) if self._started else 0.0

    def _restart_decision(self, reason: str) -> WatchdogDecision:
        now = self.wall_clock()
        attempts = self._load_restart_attempts(now)
        if len(attempts) >= self.restart_limit:
            self._transition("unavailable", "restart_suppressed")
            return WatchdogDecision(False, "restart_suppressed")
        attempts.append(now)
        self._save_restart_attempts(attempts)
        return WatchdogDecision(True, reason)

    def _load_restart_attempts(self, now: float) -> list[float]:
        if not self.restart_state_path:
            return []
        try:
            values = json.loads(self.restart_state_path.read_text())
            return [float(value) for value in values if now - float(value) < self.restart_window_seconds]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _save_restart_attempts(self, attempts: list[float]) -> None:
        if not self.restart_state_path:
            return
        self.restart_state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.restart_state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(attempts))
        os.replace(temporary, self.restart_state_path)
