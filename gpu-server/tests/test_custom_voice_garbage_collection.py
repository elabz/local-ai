import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.garbage_collection import DeletionError, execute_deletion, request_deletion
from custom_voice.registry import detach_rollback_reference, load_registry, set_version_state, stage_version


def setup_version(tmp_path: Path, *, active: bool = False) -> Path:
    registry = tmp_path / "registry.json"
    stage_version(registry_path=registry, stable_voice_id="custom-demo", version="v1", artifact_sha256="a" * 64, artifact_manifest_sha256="b" * 64, language="a")
    if active:
        set_version_state(registry_path=registry, stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64, state="active")
    return registry


def test_active_and_rollback_retained_versions_cannot_be_deleted(tmp_path: Path) -> None:
    registry = setup_version(tmp_path, active=True)
    with pytest.raises(DeletionError, match="active_artifact_deletion_forbidden"):
        request_deletion(registry_path=registry, queue_root=tmp_path / "queue", stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64, targets={"artifact": tmp_path / "artifacts" / "v1"})

    registry = setup_version(tmp_path / "second")
    with pytest.raises(DeletionError, match="rollback_artifact_deletion_forbidden"):
        request_deletion(registry_path=registry, queue_root=tmp_path / "second" / "queue", stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64, targets={"artifact": tmp_path / "second" / "artifacts" / "v1"})


def test_queued_deletion_removes_confined_targets_and_marks_deleted(tmp_path: Path) -> None:
    registry = setup_version(tmp_path)
    detach_rollback_reference(registry_path=registry, stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64)
    artifact_root = tmp_path / "artifacts"
    target = artifact_root / "custom-demo" / "v1"
    target.mkdir(parents=True)
    (target / "artifact.pt").write_bytes(b"bytes")
    request = request_deletion(registry_path=registry, queue_root=tmp_path / "queue", stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64, targets={"artifact": target})

    result = execute_deletion(registry_path=registry, queue_root=tmp_path / "queue", request_id=request["request_id"], allowed_roots={"artifact": artifact_root})

    assert result["state"] == "verified_deleted"
    assert not target.exists()
    assert load_registry(registry)["voices"]["custom-demo"]["versions"]["v1"]["state"] == "deleted"


def test_unconfined_target_is_never_removed(tmp_path: Path) -> None:
    registry = setup_version(tmp_path)
    detach_rollback_reference(registry_path=registry, stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64)
    outside = tmp_path / "outside"
    outside.mkdir()
    request = request_deletion(registry_path=registry, queue_root=tmp_path / "queue", stable_voice_id="custom-demo", version="v1", expected_artifact_sha256="a" * 64, targets={"artifact": outside})
    with pytest.raises(DeletionError, match="deletion_target_unconfined"):
        execute_deletion(registry_path=registry, queue_root=tmp_path / "queue", request_id=request["request_id"], allowed_roots={"artifact": tmp_path / "artifacts"})
    assert outside.exists()
