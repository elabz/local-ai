"""Prometheus metrics for the multimodal embedding server.

Uses the SAME metric names as gpu-server/metrics.py (inference_requests_total,
inference_duration_seconds, active_requests, model_loaded, gpu_*) so existing
Grafana dashboards and the watchdog see this service in the same format. Adds
one embedding-specific counter for items embedded by modality.
"""

import logging
import threading
from typing import Optional

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

logger = logging.getLogger(__name__)

# Request metrics (shared names with the llama.cpp GPU servers)
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

# Embedding-specific: count items embedded, split by modality.
embedding_items_total = Counter(
    "embedding_items_total",
    "Total number of items embedded",
    ["modality"],  # text | image
)

# Server metrics
active_requests_gauge = Gauge(
    "active_requests",
    "Number of active inference requests",
)

model_loaded_gauge = Gauge(
    "model_loaded",
    "Whether the model is currently loaded (1=yes, 0=no)",
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
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _collect_loop(self):
        import pynvml
        import time

        while self._running:
            try:
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    gpu_id = str(i)
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    gpu_memory_used_bytes.labels(gpu_id=gpu_id).set(mem_info.used)
                    gpu_memory_total_bytes.labels(gpu_id=gpu_id).set(mem_info.total)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_utilization_percent.labels(gpu_id=gpu_id).set(util.gpu)
                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                    gpu_temperature_celsius.labels(gpu_id=gpu_id).set(temp)
            except Exception as e:
                logger.warning(f"Error collecting GPU metrics: {e}")

            time.sleep(self.interval)


_gpu_collector: Optional[GPUMetricsCollector] = None


def start_metrics_server(port: int):
    """Start the Prometheus metrics HTTP server and GPU metrics collection."""
    global _gpu_collector
    _gpu_collector = GPUMetricsCollector()
    _gpu_collector.start()
    start_http_server(port)
    logger.info(f"Prometheus metrics server started on port {port}")
