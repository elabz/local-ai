import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.registry import (
    RegistryError,
    discover_active,
    reconcile_registry,
    registry_health,
    retire_version,
    rollback_version,
    set_version_state,
    stage_version,
)


def stage(path: Path, version: str = "v1", digest: str = "a" * 64):
    return stage_version(
        registry_path=path,
        stable_voice_id="custom-bench-speaker-001",
        version=version,
        artifact_sha256=digest,
        artifact_manifest_sha256="b" * 64,
        language="a",
    )


def test_stages_immutable_version_and_activates_exact_digest(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    assert stage(path)["state"] == "staged"
    active = set_version_state(
        registry_path=path,
        stable_voice_id="custom-bench-speaker-001",
        version="v1",
        expected_artifact_sha256="a" * 64,
        state="active",
    )
    registry = json.loads(path.read_text())
    assert active["state"] == "active"
    assert registry["voices"]["custom-bench-speaker-001"]["active_version"] == "v1"
    assert path.stat().st_mode & 0o777 == 0o600


def test_version_cannot_be_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    with pytest.raises(RegistryError, match="artifact_version_exists"):
        stage(path)


def test_new_activation_retires_prior_version(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, state="active")
    stage(path, version="v2", digest="c" * 64)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v2", expected_artifact_sha256="c" * 64, state="active")
    voice = json.loads(path.read_text())["voices"]["custom-bench-speaker-001"]
    assert voice["versions"]["v1"]["state"] == "retired"
    assert voice["active_version"] == "v2"


def test_digest_mismatch_does_not_mutate(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="artifact_digest_mismatch"):
        set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="0" * 64, state="active")
    assert path.read_bytes() == before


def test_invalid_or_built_in_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="stable_voice_id_invalid"):
        stage_version(
            registry_path=tmp_path / "registry.json",
            stable_voice_id="af_heart",
            version="v1",
            artifact_sha256="a" * 64,
            artifact_manifest_sha256="b" * 64,
            language="a",
            built_in_voice_ids={"af_heart"},
        )


def test_reconcile_digest_drift_removes_voice_from_discovery(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, state="active")
    assert "custom-bench-speaker-001" in discover_active(path)

    findings = reconcile_registry(registry_path=path, loaded_artifacts={"custom-bench-speaker-001": "0" * 64})

    assert findings == [{"voice_id": "custom-bench-speaker-001", "reason": "active_artifact_digest_mismatch"}]
    assert discover_active(path) == {}
    assert registry_health(path)["version_state_counts"]["unhealthy"] == 1


def test_rollback_health_failure_preserves_active_mapping(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, state="active")
    stage(path, version="v2", digest="c" * 64)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v2", expected_artifact_sha256="c" * 64, state="active")
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="rollback_health_failed"):
        rollback_version(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, health_probe=lambda _: False)
    assert path.read_bytes() == before


def test_healthy_rollback_switches_exact_prior_version(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, state="active")
    stage(path, version="v2", digest="c" * 64)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v2", expected_artifact_sha256="c" * 64, state="active")
    rollback_version(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, health_probe=lambda _: True)
    active = discover_active(path)
    assert active["custom-bench-speaker-001"]["version"] == "v1"


def test_retirement_rejects_active_version(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    stage(path)
    set_version_state(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64, state="active")
    with pytest.raises(RegistryError, match="active_version_retirement_forbidden"):
        retire_version(registry_path=path, stable_voice_id="custom-bench-speaker-001", version="v1", expected_artifact_sha256="a" * 64)
