import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.lifecycle import PREVIEWS_FILE, Lifecycle, LifecycleError
from custom_voice.registry import load_registry

VOICE = "custom-test-voice"


def seal(root: Path, version: str, content: bytes) -> dict:
    """A sealed version as artifact.py and run_sbom.sh leave it."""

    digest = hashlib.sha256(content).hexdigest()
    version_root = root / "artifacts" / VOICE / version
    version_root.mkdir(parents=True)
    (version_root / f"{digest}.pt").write_bytes(content)
    manifest = {"schema_version": "custom-voice-artifact.v1", "stable_voice_id": VOICE, "version": version, "language": "a", "artifact": {"sha256": digest, "size": len(content)}}
    (version_root / "manifest.json").write_text(json.dumps(manifest))
    sbom = {"packages": [{"licenseConcluded": "Apache-2.0"}, {"licenseConcluded": "NOASSERTION"}]}
    (version_root / "sbom.spdx.json").write_text(json.dumps(sbom))
    sbom_sha = hashlib.sha256((version_root / "sbom.spdx.json").read_bytes()).hexdigest()
    preview_id = hashlib.sha256(digest.encode()).hexdigest()[:32]
    (root / "previews").mkdir(exist_ok=True)
    (root / "previews" / f"{preview_id}.wav").write_bytes(b"RIFF")
    (version_root / PREVIEWS_FILE).write_text(json.dumps([preview_id]))
    attestation = {
        "attestation_id": f"hc-attest-{version}",
        "status": "approved",
        "scope": "internal_pea",
        "artifact_sha256": digest,
        "sbom_sha256": sbom_sha,
        "unresolved_license_count": 1,
        "speaker_authority_confirmed": True,
        "no_redistribution_confirmed": True,
        "license_findings_acknowledged": True,
    }
    return {
        "mutation": {"stable_voice_id": VOICE, "version": version, "artifact_sha256": digest},
        "activation": {"stable_voice_id": VOICE, "version": version, "artifact_sha256": digest, "sbom_sha256": sbom_sha, "admin_attestation_id": attestation["attestation_id"], "admin_attestation": attestation},
        "preview": root / "previews" / f"{preview_id}.wav",
    }


@pytest.fixture
def lifecycle(tmp_path: Path):
    served = {"cv_custom_test_voice"}
    life = Lifecycle(
        registry_path=tmp_path / "registry" / "registry.json",
        map_path=tmp_path / "control" / "custom-voice-map.json",
        artifact_root=tmp_path / "artifacts",
        deletion_queue=tmp_path / "registry" / "deletions",
        preview_root=tmp_path / "previews",
        discover=lambda: served,
    )
    life.served = served
    return life


def served_map(life: Lifecycle) -> dict:
    return json.loads(life.map_path.read_text())["voices"] if life.map_path.exists() else {}


def test_stage_reads_language_and_manifest_digest_from_the_seal_and_is_idempotent(tmp_path: Path, lifecycle) -> None:
    v1 = seal(tmp_path, "v1", b"one")
    assert lifecycle.stage(v1["mutation"])["state"] == "staged"
    entry = load_registry(lifecycle.registry_path)["voices"][VOICE]["versions"]["v1"]
    manifest = (tmp_path / "artifacts" / VOICE / "v1" / "manifest.json").read_bytes()
    assert entry["language"] == "a"
    assert entry["artifact_manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    assert lifecycle.stage(v1["mutation"])["state"] == "staged"


def test_activate_maps_the_voice_and_rejects_bad_evidence_without_touching_state(tmp_path: Path, lifecycle) -> None:
    v1 = seal(tmp_path, "v1", b"one")
    lifecycle.stage(v1["mutation"])
    tampered = json.loads(json.dumps(v1["activation"]))
    tampered["admin_attestation"]["unresolved_license_count"] = 0
    with pytest.raises(LifecycleError, match="activation_evidence_rejected"):
        lifecycle.activate(tampered)
    assert served_map(lifecycle) == {}
    assert lifecycle.activate(v1["activation"])["state"] == "active"
    assert served_map(lifecycle)[VOICE] == {"provider_voice_id": "cv_custom_test_voice", "language": "a"}


def test_activation_refuses_a_voice_kokoro_has_not_loaded(tmp_path: Path, lifecycle) -> None:
    v1 = seal(tmp_path, "v1", b"one")
    lifecycle.stage(v1["mutation"])
    lifecycle.served.clear()
    with pytest.raises(LifecycleError, match="activation_discovery_failed"):
        lifecycle.activate(v1["activation"])
    assert served_map(lifecycle) == {}


def test_rollback_reactivates_a_retired_version(tmp_path: Path, lifecycle) -> None:
    v1, v2 = seal(tmp_path, "v1", b"one"), seal(tmp_path, "v2", b"two")
    for version in (v1, v2):
        lifecycle.stage(version["mutation"])
        lifecycle.activate(version["activation"])
    registry = load_registry(lifecycle.registry_path)["voices"][VOICE]
    assert registry["active_version"] == "v2" and registry["versions"]["v1"]["state"] == "retired"
    assert lifecycle.rollback(v1["activation"])["state"] == "active"
    assert load_registry(lifecycle.registry_path)["voices"][VOICE]["active_version"] == "v1"


def test_retiring_the_active_version_takes_the_voice_out_of_service(tmp_path: Path, lifecycle) -> None:
    v1 = seal(tmp_path, "v1", b"one")
    lifecycle.stage(v1["mutation"])
    lifecycle.activate(v1["activation"])
    assert lifecycle.retire(v1["mutation"])["state"] == "retired"
    assert VOICE not in served_map(lifecycle)
    assert load_registry(lifecycle.registry_path)["voices"][VOICE]["active_version"] is None


def test_delete_removes_artifact_and_previews_and_refuses_the_active_version(tmp_path: Path, lifecycle) -> None:
    v1, v2 = seal(tmp_path, "v1", b"one"), seal(tmp_path, "v2", b"two")
    for version in (v1, v2):
        lifecycle.stage(version["mutation"])
    lifecycle.activate(v2["activation"])
    with pytest.raises(LifecycleError, match="active_reference_detach_forbidden"):
        lifecycle.delete(v2["mutation"])
    receipt = lifecycle.delete(v1["mutation"])
    assert receipt["state"] == "verified_deleted"
    assert not (tmp_path / "artifacts" / VOICE / "v1").exists()
    assert not v1["preview"].exists()
    assert lifecycle.deletion(receipt["request_id"]) == receipt
    assert lifecycle.delete(v1["mutation"]) == receipt
    view = lifecycle.registry_view()
    states = {item["version"]: item["state"] for item in view["voices"][0]["versions"]}
    assert states == {"v1": "deleted", "v2": "active"}
