import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.jobs import JobStore
from custom_voice.metrics import CustomVoiceMetrics


def test_metrics_cover_required_signals_without_protected_labels(tmp_path: Path) -> None:
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    jobs.create_job(caller_id="heartcode-prod", idempotency_key="request-secret-looking", intake_id="bench-speaker-001-v1", manifest_sha256="a" * 64, builder_profile="kvoicewalk-multireference.v1")
    metrics = CustomVoiceMetrics()
    metrics.refresh(jobs=jobs, registry_path=tmp_path / "registry.json", deletion_queue=tmp_path / "deletions", gpu_free_mib=3146, worker_memory_bytes=2_000_000_000)
    metrics.observe_phase("building", 120.0)
    metrics.record_drift("active_artifact_missing")
    metrics.record_activation_failure("health_failed")
    output = metrics.render().decode()
    for name in ("custom_voice_queue_depth", "custom_voice_worker_phase_duration_seconds", "custom_voice_worker_gpu_free_mib", "custom_voice_worker_memory_bytes", "custom_voice_registry_drift_total", "custom_voice_activation_failures_total", "custom_voice_cleanup_backlog"):
        assert name in output
    for protected in ("heartcode-prod", "request-secret-looking", "bench-speaker-001-v1", "aaaaaaaaaaaaaaaa"):
        assert protected not in output
