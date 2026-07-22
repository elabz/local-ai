import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.activation import ActivationError, activate_exact_digest


def test_activation_switches_exact_digest_after_health(tmp_path: Path) -> None:
    artifact = tmp_path / "voice.pt"
    artifact.write_bytes(b"internal-artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    registry = tmp_path / "registry.json"

    result = activate_exact_digest(
        registry_path=registry,
        artifact_path=artifact,
        voice_id="custom-demo",
        version="v1",
        expected_sha256=digest,
        health_probe=lambda _: True,
    )

    assert result["artifact_sha256"] == digest
    assert json.loads(registry.read_text())["custom-demo"] == result


def test_failed_health_preserves_prior_mapping(tmp_path: Path) -> None:
    artifact = tmp_path / "voice.pt"
    artifact.write_bytes(b"new-artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    registry = tmp_path / "registry.json"
    prior = {"custom-demo": {"version": "v1", "artifact_sha256": "a" * 64, "state": "active"}}
    registry.write_text(json.dumps(prior), encoding="utf-8")

    with pytest.raises(ActivationError, match="activation_health_failed"):
        activate_exact_digest(
            registry_path=registry,
            artifact_path=artifact,
            voice_id="custom-demo",
            version="v2",
            expected_sha256=digest,
            health_probe=lambda _: False,
        )

    assert json.loads(registry.read_text()) == prior


def test_digest_mismatch_never_calls_health_or_mutates(tmp_path: Path) -> None:
    artifact = tmp_path / "voice.pt"
    artifact.write_bytes(b"artifact")
    registry = tmp_path / "registry.json"
    called = False

    def probe(_: Path) -> bool:
        nonlocal called
        called = True
        return True

    with pytest.raises(ActivationError, match="artifact_digest_mismatch"):
        activate_exact_digest(
            registry_path=registry,
            artifact_path=artifact,
            voice_id="custom-demo",
            version="v1",
            expected_sha256="a" * 64,
            health_probe=probe,
        )

    assert called is False
    assert not registry.exists()
