"""Content-free Prometheus metrics for the custom-voice subsystem."""

from __future__ import annotations

from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from .jobs import STATES, JobStore
from .registry import VERSION_STATES, registry_health


class CustomVoiceMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.job_states = Gauge("custom_voice_jobs", "Jobs by safe state", ["state"], registry=self.registry)
        self.queue_depth = Gauge("custom_voice_queue_depth", "Queued custom voice jobs", registry=self.registry)
        self.worker_phase_duration = Gauge("custom_voice_worker_phase_duration_seconds", "Latest completed phase duration", ["phase"], registry=self.registry)
        self.worker_gpu_free = Gauge("custom_voice_worker_gpu_free_mib", "Visible free GPU memory", registry=self.registry)
        self.worker_memory = Gauge("custom_voice_worker_memory_bytes", "Worker container memory", registry=self.registry)
        self.registry_states = Gauge("custom_voice_registry_versions", "Registry versions by safe state", ["state"], registry=self.registry)
        self.registry_drift = Counter("custom_voice_registry_drift_total", "Registry drift findings", ["reason"], registry=self.registry)
        self.activation_failures = Counter("custom_voice_activation_failures_total", "Activation failures", ["reason"], registry=self.registry)
        self.cleanup_backlog = Gauge("custom_voice_cleanup_backlog", "Queued deletion requests", registry=self.registry)

    def refresh(self, *, jobs: JobStore, registry_path: Path, deletion_queue: Path, gpu_free_mib: int, worker_memory_bytes: int) -> None:
        rows = jobs.connection.execute("SELECT state,COUNT(*) AS count FROM jobs GROUP BY state").fetchall()
        counts = {row["state"]: row["count"] for row in rows}
        for state in sorted(STATES):
            self.job_states.labels(state).set(counts.get(state, 0))
        self.queue_depth.set(counts.get("queued", 0))
        health = registry_health(registry_path)
        for state in sorted(VERSION_STATES):
            self.registry_states.labels(state).set(health["version_state_counts"].get(state, 0))
        self.worker_gpu_free.set(max(0, gpu_free_mib))
        self.worker_memory.set(max(0, worker_memory_bytes))
        backlog = 0
        if deletion_queue.exists():
            backlog = sum(1 for path in deletion_queue.iterdir() if path.is_file() and path.suffix == ".json" and b'"state":"queued"' in path.read_bytes())
        self.cleanup_backlog.set(backlog)

    def observe_phase(self, phase: str, duration_seconds: float) -> None:
        if phase not in {"validating", "preprocessing", "building", "evaluating"}:
            raise ValueError("metric_phase_invalid")
        self.worker_phase_duration.labels(phase).set(max(0, duration_seconds))

    def record_drift(self, reason: str) -> None:
        if reason not in {"active_artifact_missing", "active_artifact_digest_mismatch", "unexpected_custom_artifact"}:
            raise ValueError("metric_reason_invalid")
        self.registry_drift.labels(reason).inc()

    def record_activation_failure(self, reason: str) -> None:
        if reason not in {"digest_mismatch", "health_failed", "supply_chain_failed", "provider_unavailable"}:
            raise ValueError("metric_reason_invalid")
        self.activation_failures.labels(reason).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)
