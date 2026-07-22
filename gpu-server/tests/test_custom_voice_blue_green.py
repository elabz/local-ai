import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.blue_green import BlueGreenError, ProviderOperations, activate_blue_green, provider_voice_id, publish_snapshot
from custom_voice.registry import load_registry, stage_version


def setup_activation(tmp_path: Path, *, discover=True, audio=b"RIFF"):
    artifact = tmp_path / "artifact.pt"
    artifact.write_bytes(b"internal tensor")
    artifact.chmod(0o600)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    registry = tmp_path / "registry.json"
    stage_version(registry_path=registry, stable_voice_id="custom-demo", version="v1", artifact_sha256=digest, artifact_manifest_sha256="b" * 64, language="a")
    events = []
    ops = ProviderOperations(
        active_slot=lambda: "blue",
        wait_drained=lambda slot: events.append(("drain", slot)) is None or True,
        start=lambda slot, root: events.append(("start", slot, root)),
        stop=lambda slot: events.append(("stop", slot)),
        discover=lambda slot: {"cv_custom_demo"} if discover else set(),
        synthesize=lambda slot, voice: audio,
        switch_traffic=lambda slot: events.append(("switch", slot)),
    )
    return artifact, digest, registry, events, ops


def test_probes_candidate_then_switches_registry_and_stops_old_slot(tmp_path: Path) -> None:
    artifact, digest, registry, events, ops = setup_activation(tmp_path)
    result = activate_blue_green(registry_path=registry, snapshot_root=tmp_path / "snapshots", stable_voice_id="custom-demo", version="v1", artifact_path=artifact, expected_sha256=digest, active_artifacts={}, operations=ops)
    assert result["slot"] == "green"
    assert events[-2:] == [("switch", "green"), ("stop", "blue")]
    assert (tmp_path / "snapshots" / "green" / "cv_custom_demo.pt").stat().st_mode & 0o777 == 0o444
    assert load_registry(registry)["voices"]["custom-demo"]["active_version"] == "v1"


def test_failed_candidate_never_switches_traffic_or_registry(tmp_path: Path) -> None:
    artifact, digest, registry, events, ops = setup_activation(tmp_path, discover=False)
    with pytest.raises(BlueGreenError, match="activation_discovery_failed"):
        activate_blue_green(registry_path=registry, snapshot_root=tmp_path / "snapshots", stable_voice_id="custom-demo", version="v1", artifact_path=artifact, expected_sha256=digest, active_artifacts={}, operations=ops)
    assert ("switch", "green") not in events
    assert events[-1] == ("stop", "green")
    assert load_registry(registry)["voices"]["custom-demo"]["active_version"] is None


def test_reserved_stable_id_maps_to_non_blend_provider_id() -> None:
    assert provider_voice_id("custom-dima") == "cv_custom_dima"


def test_read_only_snapshot_can_be_replaced(tmp_path: Path) -> None:
    artifact, digest, *_ = setup_activation(tmp_path)
    root = tmp_path / "replace-snapshots"
    publish_snapshot(snapshot_root=root, slot="green", artifacts={"custom-demo": (artifact, digest)})
    publish_snapshot(snapshot_root=root, slot="green", artifacts={"custom-demo": (artifact, digest)})
    assert (root / "green" / "cv_custom_demo.pt").stat().st_mode & 0o777 == 0o444


def test_failed_registry_commit_restores_old_traffic(tmp_path: Path) -> None:
    artifact, digest, registry, events, ops = setup_activation(tmp_path)
    with pytest.raises(BlueGreenError, match="registry_switch_failed"):
        activate_blue_green(registry_path=registry, snapshot_root=tmp_path / "snapshots", stable_voice_id="custom-demo", version="v2", artifact_path=artifact, expected_sha256=digest, active_artifacts={}, operations=ops)
    assert events[-2:] == [("switch", "blue"), ("stop", "green")]
