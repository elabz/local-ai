import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.preview import PreviewError, read_protected_preview, stage_for_review
from custom_voice.registry import discover_active


def test_preview_read_requires_scope_and_exact_digest(tmp_path: Path) -> None:
    root = tmp_path / "previews"
    root.mkdir(mode=0o700)
    preview_id = "a" * 32
    preview = root / f"{preview_id}.wav"
    preview.write_bytes(b"private audio")
    preview.chmod(0o600)
    digest = hashlib.sha256(preview.read_bytes()).hexdigest()
    with pytest.raises(PreviewError, match="preview_forbidden"):
        read_protected_preview(preview_root=root, preview_id=preview_id, expected_sha256=digest, scopes=set())
    assert read_protected_preview(preview_root=root, preview_id=preview_id, expected_sha256=digest, scopes={"custom_voice.preview.read"}) == b"private audio"


def test_staging_does_not_publish_voice(tmp_path: Path) -> None:
    artifact_digest = "a" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "stable_voice_id": "custom-bench-speaker-001",
        "version": "v1",
        "language": "a",
        "artifact": {"sha256": artifact_digest},
    }))
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({
        "artifact_sha256": artifact_digest,
        "objective_outcome": "pass",
        "human_naturalness_outcome": "pending",
        "samples": [{"preview_id": "b" * 32, "preview_sha256": "c" * 64}],
    }))
    compatibility = tmp_path / "compatibility.json"
    compatibility.write_text(json.dumps({"artifact_sha256": artifact_digest, "outcome": "pass"}))
    registry = tmp_path / "registry.json"

    staged = stage_for_review(registry_path=registry, artifact_manifest_path=manifest, evaluation_path=evaluation, compatibility_path=compatibility)

    assert staged["state"] == "staged"
    assert staged["human_naturalness_outcome"] == "pending"
    assert discover_active(registry) == {}


def test_staging_requires_matching_compatibility_digest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stable_voice_id": "custom-demo", "version": "v1", "language": "a", "artifact": {"sha256": "a" * 64}}))
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({"artifact_sha256": "a" * 64, "objective_outcome": "pass", "samples": []}))
    compatibility = tmp_path / "compatibility.json"
    compatibility.write_text(json.dumps({"artifact_sha256": "b" * 64, "outcome": "pass"}))
    with pytest.raises(PreviewError, match="staging_digest_mismatch"):
        stage_for_review(registry_path=tmp_path / "registry.json", artifact_manifest_path=manifest, evaluation_path=evaluation, compatibility_path=compatibility)
