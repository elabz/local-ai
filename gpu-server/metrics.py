"""Prometheus metrics for GPU server."""

import logging
import threading
from typing import Optional

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
    REGISTRY,
)

logger = logging.getLogger(__name__)

# Request metrics
inference_requests_total = Counter(
    "inference_requests_total",
    "Total number of inference requests",
    ["endpoint", "status"],
)

inference_duration_seconds = Histogram(
    "inference_duration_seconds",
    "Inference request duration in seconds",
    ["endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

inference_tokens_total = Counter(
    "inference_tokens_total",
    "Total number of tokens generated",
    ["type"],
)

# Admission control (bounded queue in front of the single inference slot)
inference_admission_total = Counter(
    "inference_admission_total",
    "Admission decisions: admitted (slot free on arrival), queued (waited for a slot), rejected (wait bound exceeded)",
    ["status"],
)
inference_admission_wait_seconds = Histogram(
    "inference_admission_wait_seconds",
    "Seconds a request waited for an inference slot before being admitted or rejected",
    buckets=[0.05, 0.25, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0],
)

# Server metrics
active_requests_gauge = Gauge(
    "active_requests",
    "Number of active inference requests",
)

model_loaded_gauge = Gauge(
    "model_loaded",
    "Whether a model is currently loaded (1=yes, 0=no)",
)

# GPU metrics
gpu_memory_used_bytes = Gauge(
    "gpu_memory_used_bytes",
    "GPU memory used in bytes",
    ["gpu_id"],
)

gpu_memory_total_bytes = Gauge(
    "gpu_memory_total_bytes",
    "Total GPU memory in bytes",
    ["gpu_id"],
)

gpu_utilization_percent = Gauge(
    "gpu_utilization_percent",
    "GPU utilization percentage",
    ["gpu_id"],
)

gpu_temperature_celsius = Gauge(
    "gpu_temperature_celsius",
    "GPU temperature in Celsius",
    ["gpu_id"],
)

gpu_readiness = Gauge(
    "gpu_readiness",
    "Whether configured GPU readiness is ready (1=yes)",
)
gpu_readiness_transitions_total = Counter(
    "gpu_readiness_transitions_total",
    "GPU readiness transitions by bounded state and reason",
    ["state", "reason"],
)

backend_state = Gauge(
    "backend_state", "Current backend availability state", ["state", "reason"],
)
backend_state_transitions_total = Counter(
    "backend_state_transitions_total", "Backend state transitions", ["state", "reason"],
)
backend_in_flight_requests = Gauge(
    "backend_in_flight_requests", "Bounded in-flight inference requests",
)
watchdog_probe_failures_total = Counter(
    "watchdog_probe_failures_total", "Watchdog probe failures", ["reason"],
)
watchdog_restart_decisions_total = Counter(
    "watchdog_restart_decisions_total", "Watchdog restart decisions", ["decision", "reason"],
)
llama_child_exits_total = Counter(
    "llama_child_exits_total", "Unexpected llama.cpp child exits",
)
backend_recovery_seconds = Histogram(
    "backend_recovery_seconds", "Time from wrapper startup to llama.cpp readiness",
    buckets=[5, 10, 20, 30, 45, 60, 90, 120, 180, 300],
)


_backend_state_current = None


def record_backend_state(state: str, reason: str) -> None:
    global _backend_state_current
    safe_state = state if state in {"starting", "ready", "busy", "degraded", "unavailable"} else "unavailable"
    safe_reason = reason if reason in {
        "starting", "ready", "inference_active", "busy_probe_timeout",
        "idle_probe_failure", "stuck_request", "child_exit", "gpu_unavailable",
        "restart_suppressed", "recovering", "capacity_exhausted",
    } else "idle_probe_failure"
    if _backend_state_current is not None:
        backend_state.labels(state=_backend_state_current[0], reason=_backend_state_current[1]).set(0)
    backend_state.labels(state=safe_state, reason=safe_reason).set(1)
    _backend_state_current = (safe_state, safe_reason)
    backend_state_transitions_total.labels(state=safe_state, reason=safe_reason).inc()


def record_gpu_readiness(state: str, reason: str) -> None:
    if state not in {"starting", "ready", "unavailable"}:
        state = "unavailable"
    if reason not in {
        "disabled", "starting", "ready", "model_unavailable", "gpu_query_failed",
        "gpu_identity_mismatch", "gpu_memory_failed", "gpu_execution_failed",
    }:
        reason = "gpu_query_failed"
    gpu_readiness.set(1 if state == "ready" else 0)
    gpu_readiness_transitions_total.labels(state=state, reason=reason).inc()


class GPUMetricsCollector:
    """Collect GPU metrics using pynvml."""

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start collecting GPU metrics."""
        try:
            import pynvml
            pynvml.nvmlInit()
            self._running = True
            self._thread = threading.Thread(target=self._collect_loop, daemon=True)
            self._thread.start()
            logger.info("GPU metrics collection started")
        except Exception as e:
            logger.warning(f"Could not initialize GPU metrics: {e}")

    def stop(self):
        """Stop collecting GPU metrics."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _collect_loop(self):
        """Collect GPU metrics in a loop."""
        import pynvml
        import time

        while self._running:
            try:
                device_count = pynvml.nvmlDeviceGetCount()

                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    gpu_id = str(i)

                    # Memory
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    gpu_memory_used_bytes.labels(gpu_id=gpu_id).set(mem_info.used)
                    gpu_memory_total_bytes.labels(gpu_id=gpu_id).set(mem_info.total)

                    # Utilization
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_utilization_percent.labels(gpu_id=gpu_id).set(util.gpu)

                    # Temperature
                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                    gpu_temperature_celsius.labels(gpu_id=gpu_id).set(temp)

            except Exception as e:
                logger.warning(f"Error collecting GPU metrics: {e}")

            time.sleep(self.interval)


# Global GPU metrics collector
_gpu_collector: Optional[GPUMetricsCollector] = None


def start_metrics_server(port: int):
    """Start the Prometheus metrics HTTP server."""
    global _gpu_collector

    # Start GPU metrics collection
    _gpu_collector = GPUMetricsCollector()
    _gpu_collector.start()

    # Start HTTP server for metrics
    start_http_server(port)
    logger.info(f"Prometheus metrics server started on port {port}")


def get_gpu_info() -> dict:
    """Get current GPU information."""
    try:
        import pynvml

        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()

        gpus = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

            gpus.append({
                "id": i,
                "name": name,
                "memory_used_mb": mem_info.used // (1024 * 1024),
                "memory_total_mb": mem_info.total // (1024 * 1024),
                "memory_free_mb": mem_info.free // (1024 * 1024),
                "utilization_percent": util.gpu,
                "temperature_celsius": temp,
            })

        return {"gpus": gpus, "count": device_count}

    except Exception as e:
        logger.warning(f"Could not get GPU info: {e}")
        return {"gpus": [], "count": 0, "error": str(e)}
