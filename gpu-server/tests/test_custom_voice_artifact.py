import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.artifact import ArtifactError, seal_artifact


def private_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o600)


def build_inputs(tmp_path: Path) -> tuple[Path, Path]:
    artifact = tmp_path / "artifact.pt"
    private_file(artifact, b"internal tensor")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = tmp_path / "result.json"
    private_file(
        result,
        json.dumps(
            {
                "schema_version": "custom-voice-build-result.v1",
                "artifact_sha256": digest,
                "artifact_size": artifact.stat().st_size,
                "kokoro_runtime_image": "runtime@sha256:" + "1" * 64,
                "build_plan_sha256": "2" * 64,
                "manifest_sha256": "3" * 64,
                "builder_profile": "kvoicewalk-multireference.v1",
                "builder_revision": "4" * 40,
                "worker_image_digest": "5" * 64,
                "seed": 42,
                "steps": 10_000,
                "duration_seconds": 123.5,
                "resource_observations": {
                    "peak_observed_gpu_used_mib": 3_000,
                    "minimum_observed_gpu_free_mib": 2_000,
                    "peak_worker_rss_mib": 2_100.5,
                    "peak_private_job_bytes": 5_000_000,
                },
            }
        ).encode(),
    )
    return artifact, result


def test_seals_content_addressed_private_artifact(tmp_path: Path) -> None:
    artifact, result = build_inputs(tmp_path)

    manifest = seal_artifact(
        artifact=artifact,
        build_result=result,
        store=tmp_path / "store",
        stable_voice_id="custom-bench-speaker-001",
        version="v1",
        language="a",
    )

    version = tmp_path / "store" / "custom-bench-speaker-001" / "v1"
    digest = manifest["artifact"]["sha256"]
    assert (version / f"{digest}.pt").read_bytes() == b"internal tensor"
    assert json.loads((version / "manifest.json").read_text()) == manifest
    assert version.stat().st_mode & 0o777 == 0o700
    assert (version / "manifest.json").stat().st_mode & 0o777 == 0o600


def test_rejects_digest_mismatch_without_publishing(tmp_path: Path) -> None:
    artifact, result = build_inputs(tmp_path)
    data = json.loads(result.read_text())
    data["artifact_sha256"] = "0" * 64
    private_file(result, json.dumps(data).encode())

    with pytest.raises(ArtifactError, match="artifact_result_mismatch"):
        seal_artifact(
            artifact=artifact,
            build_result=result,
            store=tmp_path / "store",
            stable_voice_id="custom-bench-speaker-001",
            version="v1",
            language="a",
        )

    assert not (tmp_path / "store" / "custom-bench-speaker-001" / "v1").exists()


def test_rejects_existing_version(tmp_path: Path) -> None:
    artifact, result = build_inputs(tmp_path)
    arguments = dict(
        artifact=artifact,
        build_result=result,
        store=tmp_path / "store",
        stable_voice_id="custom-bench-speaker-001",
        version="v1",
        language="a",
    )
    seal_artifact(**arguments)
    with pytest.raises(ArtifactError, match="artifact_version_exists"):
        seal_artifact(**arguments)


def test_rejects_old_result_without_resource_evidence(tmp_path: Path) -> None:
    artifact, result = build_inputs(tmp_path)
    data = json.loads(result.read_text())
    del data["resource_observations"]
    private_file(result, json.dumps(data).encode())
    with pytest.raises(ArtifactError, match="build_result_resource_evidence_missing"):
        seal_artifact(artifact=artifact, build_result=result, store=tmp_path / "store", stable_voice_id="custom-demo", version="v1", language="a")
