import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.worker import ResourceObservations, enforce_deadline, enforce_gpu_admission, enforce_not_cancelled, exclusive_worker, load_build_plan, quiet_call


def write_plan(path: Path, samples: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "builder_profile": "kvoicewalk-multireference.v1",
                "manifest_sha256": "a" * 64,
                "seed": 42,
                "samples": samples,
            }
        ),
        encoding="utf-8",
    )


def test_plan_loads_only_adaptation_references(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    samples = []
    for sample_id, role in (("adapt-001", "adaptation"), ("adapt-002", "adaptation"), ("heldout-001", "heldout")):
        audio = workspace / f"{sample_id}.wav"
        transcript = workspace / f"{sample_id}.txt"
        audio.write_bytes(b"wav")
        transcript.write_text("words", encoding="utf-8")
        samples.append(
            {
                "sample_id": sample_id,
                "role": role,
                "audio_path": audio.name,
                "transcript_path": transcript.name,
            }
        )
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, samples)

    _, references = load_build_plan(plan_path, workspace)

    assert [sample_id for sample_id, _, _ in references] == ["adapt-001", "adapt-002"]


def test_plan_excludes_declared_adaptation_outlier(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    samples = []
    for sample_id in ("adapt-001", "adapt-002", "adapt-003"):
        audio = workspace / f"{sample_id}.wav"
        transcript = workspace / f"{sample_id}.txt"
        audio.write_bytes(b"wav")
        transcript.write_text("words", encoding="utf-8")
        samples.append({"sample_id": sample_id, "role": "adaptation", "audio_path": audio.name, "transcript_path": transcript.name})
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, samples)
    plan = json.loads(plan_path.read_text())
    plan["excluded_adaptation_sample_ids"] = ["adapt-001"]
    plan_path.write_text(json.dumps(plan))

    _, references = load_build_plan(plan_path, workspace)

    assert [sample_id for sample_id, _, _ in references] == ["adapt-002", "adapt-003"]


def test_plan_rejects_workspace_escape(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    write_plan(
        plan_path,
        [
            {"sample_id": "a", "role": "adaptation", "audio_path": "../a.wav", "transcript_path": "a.txt"},
            {"sample_id": "b", "role": "adaptation", "audio_path": "b.wav", "transcript_path": "b.txt"},
        ],
    )
    with pytest.raises(ValueError, match="workspace_path_invalid"):
        load_build_plan(plan_path, tmp_path)


def test_gpu_admission_defers_when_reserve_is_missing(monkeypatch) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="4096\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(RuntimeError, match="gpu_admission_deferred"):
        enforce_gpu_admission(5_000)


def test_gpu_admission_accepts_one_visible_gpu(monkeypatch) -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="5500\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    assert enforce_gpu_admission(5_000) == 5_500


def test_third_party_output_is_contained(capsys) -> None:
    def noisy(value):
        print("/private/path transcript words")
        return value

    assert quiet_call(noisy, 42) == 42
    assert capsys.readouterr().out == ""


def test_expired_worker_deadline_fails_closed() -> None:
    with pytest.raises(TimeoutError, match="worker_timeout"):
        enforce_deadline(0)


def test_worker_lock_enforces_concurrency_one(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    with exclusive_worker(lock):
        with pytest.raises(RuntimeError, match="worker_concurrency_exhausted"):
            with exclusive_worker(lock):
                pass


def test_cancellation_sentinel_is_cooperative(tmp_path: Path) -> None:
    sentinel = tmp_path / "cancel.requested"
    enforce_not_cancelled(sentinel)
    sentinel.touch()
    with pytest.raises(RuntimeError, match="worker_cancelled"):
        enforce_not_cancelled(sentinel)


def test_launcher_enforces_isolation_and_read_only_intake() -> None:
    launcher = Path(__file__).resolve().parents[1] / "custom_voice" / "run_worker.sh"
    content = launcher.read_text(encoding="utf-8")
    for option in ("--runtime nvidia", "--cpus 2", "--memory 4g", "--memory-swap 4g", "--pids-limit 256", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges"):
        assert option in content
    assert "NVIDIA_VISIBLE_DEVICES=GPU-f417c539-26db-94e9-4c8f-c5a775291988" in content
    assert "custom-voice-intake:/data/custom-voice-intake:ro" in content
    assert 'actual_image_digest=$(docker image inspect' in content
    assert 'CUSTOM_VOICE_PREFLIGHT_ONLY:-0' in content
    assert '-v "$CUSTOM_VOICE_PRIVATE_ROOT:/data"' not in content


def test_resource_observations_record_safe_peak_metrics(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    (workspace / "sample.bin").write_bytes(b"x" * 10)
    readings = iter([(8_000, 5_000), (8_000, 4_000)])
    monkeypatch.setattr("custom_voice.worker.gpu_memory_mib", lambda: next(readings))
    observations = ResourceObservations(workspace, output)
    observations.sample()
    (output / "checkpoint.pt").write_bytes(b"x" * 20)
    observations.sample()
    result = observations.result()
    assert result["peak_observed_gpu_used_mib"] == 4_000
    assert result["minimum_observed_gpu_free_mib"] == 4_000
    assert result["peak_private_job_bytes"] == 30
    assert result["peak_worker_rss_mib"] > 0


def test_worker_publishes_only_private_result_files() -> None:
    worker = (Path(__file__).resolve().parents[1] / "custom_voice" / "worker.py").read_text(encoding="utf-8")
    assert 'checkpoint_path = output / "checkpoint.v2.json"' in worker
    assert "write_checkpoint(checkpoint_path, payload)" in worker
    assert "artifact.chmod(0o600)" in worker
    assert "preview.chmod(0o600)" in worker
    assert "result_path.chmod(0o600)" in worker
    assert 'config="/app/api/src/models/v1_0/config.json"' in worker
    assert 'model="/app/api/src/models/v1_0/kokoro-v1_0.pth"' in worker


def test_postbuild_uses_sealed_artifact_and_isolated_runners() -> None:
    script = (Path(__file__).resolve().parents[1] / "custom_voice" / "run_postbuild.sh").read_text(encoding="utf-8")
    assert "python3 -m custom_voice.artifact" in script
    assert "--network none --read-only --cap-drop ALL" in script
    assert "--asr-url http://speech-stt:8000/v1/audio/transcriptions" in script
    assert '--min-similarity "$CUSTOM_VOICE_MIN_SIMILARITY"' in script
    assert script.count("--runtime nvidia") == 2
    assert '"$workspace:/workspace:ro"' in script
    assert '"$preview_root:/previews:rw"' in script


def test_worker_runtime_caches_are_confined_to_tmpfs() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "custom_voice" / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "HOME=/tmp" in dockerfile
    assert "XDG_CACHE_HOME=/tmp/cache" in dockerfile
    assert "NUMBA_CACHE_DIR=/tmp/numba" in dockerfile
