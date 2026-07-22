"""Atomic provider-slot routing and in-flight request draining."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SLOTS = frozenset({"blue", "green"})


class TrafficError(RuntimeError):
    """Safe provider-routing failure."""


class SlotRouter:
    """Pin each request to one slot and drain old requests before replacement."""

    def __init__(self, state_path: Path, *, initial_slot: str = "blue") -> None:
        if initial_slot not in SLOTS:
            raise TrafficError("provider_slot_invalid")
        self.state_path = state_path
        self._condition = threading.Condition()
        self._in_flight = {slot: 0 for slot in SLOTS}
        if not state_path.exists():
            self.switch(initial_slot)

    def active_slot(self) -> str:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            slot = value["active_slot"]
        except (OSError, KeyError, json.JSONDecodeError, TypeError) as error:
            raise TrafficError("provider_route_invalid") from error
        if slot not in SLOTS:
            raise TrafficError("provider_route_invalid")
        return slot

    def switch(self, slot: str) -> None:
        if slot not in SLOTS:
            raise TrafficError("provider_slot_invalid")
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".provider-route-", dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                json.dump({"schema_version": "custom-voice-provider-route.v1", "active_slot": slot}, temporary, sort_keys=True, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.state_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @contextmanager
    def request_slot(self) -> Iterator[str]:
        """Keep a request on the slot selected when it started."""

        with self._condition:
            slot = self.active_slot()
            self._in_flight[slot] += 1
        try:
            yield slot
        finally:
            with self._condition:
                self._in_flight[slot] -= 1
                self._condition.notify_all()

    def wait_drained(self, slot: str, *, timeout: float) -> bool:
        if slot not in SLOTS or timeout < 0:
            raise TrafficError("provider_drain_invalid")
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._in_flight[slot]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def activity(self) -> dict[str, int]:
        with self._condition:
            return dict(self._in_flight)
