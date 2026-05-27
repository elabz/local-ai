"""Prometheus metrics for the image-search service.

No GPU metrics (this service has no GPU) — it tracks request counts/latency for
ingest and search plus the count of indexed items, so the existing Prometheus
stack can scrape it in the same format as the GPU servers.
"""

import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

# endpoint = ingest | search_text | search_image ; status = success|bad_request|error|started
search_requests_total = Counter(
    "image_search_requests_total",
    "Total image-search/ingest requests",
    ["endpoint", "status"],
)

search_duration_seconds = Histogram(
    "image_search_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

active_requests_gauge = Gauge(
    "image_search_active_requests",
    "Number of in-flight image-search/ingest requests",
)

# Items successfully embedded + upserted into the index.
items_indexed_total = Counter(
    "image_search_items_indexed_total",
    "Total items embedded and indexed",
)

# 1 once the index is reachable and dimension-verified at startup.
ready_gauge = Gauge(
    "image_search_ready",
    "Whether the service has verified the embedding endpoint and ES index (1=yes)",
)


def start_metrics_server(port: int):
    start_http_server(port)
    logger.info(f"Prometheus metrics server started on port {port}")
