"""Fail-closed, content-free GPU readiness primitives."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

SAFE_REASONS = frozenset({
    "disabled", "starting", "ready", "model_unavailable", "gpu_query_failed",
    "gpu_identity_mismatch", "gpu_memory_failed", "gpu_execution_failed",
})


@dataclass(frozen=True)
class ReadinessSnapshot:
    state: str
    reason: str
    consecutive_successes: int


class GPUReadiness:
    """Immediate failure and hysteretic recovery shared by GPU services."""

    def __init__(self, *, enabled: bool, recovery_successes: int = 2, on_transition: Callable[[str, str], None] | None = None):
        if recovery_successes < 2 or recovery_successes > 10:
            raise ValueError("gpu_recovery_bounds_invalid")
        self.enabled = enabled
        self.recovery_successes = recovery_successes
        self._lock = threading.Lock()
        self._state = "starting" if enabled else "ready"
        self._reason = "starting" if enabled else "disabled"
        self._successes = 0
        self._on_transition = on_transition

    def snapshot(self) -> ReadinessSnapshot:
        with self._lock:
            return ReadinessSnapshot(self._state, self._reason, self._successes)

    @property
    def ready(self) -> bool:
        return self.snapshot().state == "ready"

    def success(self) -> ReadinessSnapshot:
        if not self.enabled:
            return self.snapshot()
        transition = None
        with self._lock:
            self._successes = min(self.recovery_successes, self._successes + 1)
            if self._successes >= self.recovery_successes:
                transition = self._set_locked("ready", "ready")
            snapshot = ReadinessSnapshot(self._state, self._reason, self._successes)
        self._emit(transition)
        return snapshot

    def fail(self, reason: str) -> ReadinessSnapshot:
        if reason not in SAFE_REASONS or reason in {"ready", "disabled", "starting"}:
            reason = "gpu_query_failed"
        transition = None
        with self._lock:
            self._successes = 0
            transition = self._set_locked("unavailable", reason)
            snapshot = ReadinessSnapshot(self._state, self._reason, self._successes)
        self._emit(transition)
        return snapshot

    def require_ready(self) -> None:
        snapshot = self.snapshot()
        if snapshot.state != "ready":
            raise GPUUnavailable(snapshot.reason)

    def _set_locked(self, state: str, reason: str):
        if self._state == state and self._reason == reason:
            return None
        self._state, self._reason = state, reason
        return state, reason

    def _emit(self, transition) -> None:
        if transition and self._on_transition:
            self._on_transition(*transition)


class GPUUnavailable(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason if reason in SAFE_REASONS else "gpu_query_failed"
        super().__init__(self.reason)


def is_cuda_device_error(error: BaseException) -> bool:
    """Classify CUDA context/device failures without returning exception text."""
    name = type(error).__name__.lower()
    module = type(error).__module__.lower()
    message = str(error).lower()
    return "cuda" in name or "cuda" in module or any(token in message for token in (
        "cuda", "device-side assert", "device is lost", "device unavailable",
        "invalid device ordinal", "unspecified launch failure",
    ))


def probe_nvidia_smi(expected_uuid: str, *, runner=subprocess.run) -> str | None:
    """Return a safe reason or None; never return raw command output."""
    if not expected_uuid.startswith("GPU-") or len(expected_uuid) > 80:
        return "gpu_identity_mismatch"
    try:
        completed = runner(
            ["nvidia-smi", "--query-gpu=uuid,memory.total", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        rows = [tuple(part.strip() for part in row.split(",", 1)) for row in completed.stdout.splitlines() if "," in row]
    except (OSError, subprocess.SubprocessError):
        return "gpu_query_failed"
    match = next((memory for uuid, memory in rows if uuid == expected_uuid), None)
    if match is None:
        return "gpu_identity_mismatch"
    try:
        if int(match) <= 0:
            return "gpu_memory_failed"
    except ValueError:
        return "gpu_memory_failed"
    return None


def configured_gpu_health_enabled() -> bool:
    return os.getenv("GPU_HEALTH_ENABLED", "0") == "1"


def probe_torch_gpu(expected_uuid: str, *, lock=None) -> str | None:
    """Verify identity, memory, and a tiny CUDA execution without input data."""
    if not expected_uuid.startswith("GPU-") or len(expected_uuid) > 80:
        return "gpu_identity_mismatch"
    try:
        import pynvml
        import torch
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            return "gpu_query_failed"
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByUUID(expected_uuid)
        discovered = pynvml.nvmlDeviceGetUUID(handle)
        if isinstance(discovered, bytes):
            discovered = discovered.decode("ascii", "strict")
        if discovered != expected_uuid:
            return "gpu_identity_mismatch"
    except Exception as error:
        if type(error).__name__ in {"NVMLError_NotFound", "NVMLError_InvalidArgument"}:
            return "gpu_identity_mismatch"
        return "gpu_query_failed"
    try:
        if int(pynvml.nvmlDeviceGetMemoryInfo(handle).total) <= 0:
            return "gpu_memory_failed"
    except Exception:
        return "gpu_memory_failed"
    try:
        context = lock if lock is not None else _NullLock()
        with context:
            value = torch.ones(1, device="cuda").add_(1).item()
            torch.cuda.synchronize()
        if value != 2:
            return "gpu_execution_failed"
        return None
    except Exception:
        return "gpu_execution_failed"


class _NullLock:
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False


class GPUHealthMonitor:
    def __init__(self, readiness: GPUReadiness, probe: Callable[[], str | None], *, interval: float = 5.0):
        self.readiness = readiness
        self.probe = probe
        self.interval = max(1.0, min(60.0, interval))
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> ReadinessSnapshot:
        reason = self.probe()
        return self.readiness.fail(reason) if reason else self.readiness.success()

    def start(self) -> None:
        if not self.readiness.enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gpu-health")
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)

    def _loop(self) -> None:
        while not self._stopped.is_set():
            self.check()
            self._stopped.wait(self.interval)
