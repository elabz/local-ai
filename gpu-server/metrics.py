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
