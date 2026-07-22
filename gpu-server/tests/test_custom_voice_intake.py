import hashlib
import json
import os
import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.intake import IntakeError, IntakeProfile, _copy_fd, prepare_workspace

PROFILE = IntakeProfile(
    adaptation_count=2,
    heldout_count=1,
    min_duration_seconds=0.5,
    max_duration_seconds=2.0,
)


def write_wav(path: Path) -> None:
    samples = [int(2_000 * ((index % 20) - 10) / 10) for index in range(16_000)]
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    path.chmod(0o600)


def build_intake(root: Path) -> tuple[Path, str]:
    intake = root / "speaker-001"
    intake.mkdir(mode=0o700)
    samples = []
    for sample_id, role in (("adapt-001", "adaptation"), ("adapt-002", "adaptation"), ("heldout-001", "heldout")):
        audio = intake / f"{sample_id}.wav"
        transcript = intake / f"{sample_id}.txt"
        write_wav(audio)
        transcript.write_text("one two", encoding="utf-8")
        transcript.chmod(0o600)
        samples.append(
            {
                "sample_id": sample_id,
                "role": role,
                "audio_path": audio.name,
                "transcript_path": transcript.name,
                "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                "sample_rate_hz": 16_000,
                "channels": 1,
                "encoding": "pcm_s16le",
            }
        )
    manifest = intake / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "benchmark-intake.v1",
                "speaker_id": "speaker-001",
                "authorization_id": "hc-consent-test",
                "authorization_scope": "production",
                "language": "en-US",
                "samples": samples,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    return intake, hashlib.sha256(manifest.read_bytes()).hexdigest()


def prepare(root: Path, digest: str, workspace_root: Path) -> dict[str, object]:
    return prepare_workspace(
        intake_root=root,
        intake_id="speaker-001",
        expected_manifest_sha256=digest,
        workspace_root=workspace_root,
        job_id="job-001",
        seed=42,
        expected_uid=os.getuid(),
        profile=PROFILE,
    )


def test_prepares_private_deterministic_workspace(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    _, digest = build_intake(intake_root)
    workspace_root = tmp_path / "workspaces"

    result = prepare(intake_root, digest, workspace_root)

    workspace = workspace_root / "job-001"
    plan = json.loads((workspace / "build-plan.json").read_text())
    assert result["sample_count"] == 3
    assert [sample["role"] for sample in plan["samples"]] == ["adaptation", "adaptation", "heldout"]
    assert plan["step_limit"] == 10_000
    assert plan["population_limit"] == 10
    assert plan["checkpoint_interval"] == 100
    assert plan["runtime_free_vram_mib"] == 1_024
    assert plan["max_duration_seconds"] == 21_600
    assert plan["active_work_budget_seconds"] == 21_600
    assert plan["maximum_wall_lifetime_seconds"] == 86_400
    assert plan["scoring_backend"] == "early_rejection_sequential"
    assert plan["batch_backend_enabled"] is False
    assert plan["plateau_policy"] is None
    assert plan["require_live_health"] is True
    assert plan["require_live_activity"] is True
    assert not (workspace / "raw").exists()
    with wave.open(str(workspace / "samples" / "adapt-001.wav"), "rb") as audio:
        assert audio.getframerate() == 24_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
    assert (workspace.stat().st_mode & 0o777) == 0o700
    assert ((workspace / "build-plan.json").stat().st_mode & 0o777) == 0o600


def test_same_seed_and_inputs_produce_identical_plans_and_derivatives(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    _, digest = build_intake(intake_root)
    workspace_root = tmp_path / "workspaces"
    common = dict(intake_root=intake_root, intake_id="speaker-001", expected_manifest_sha256=digest, workspace_root=workspace_root, seed=42, expected_uid=os.getuid(), profile=PROFILE)
    prepare_workspace(job_id="repeat-a", **common)
    prepare_workspace(job_id="repeat-b", **common)
    first = workspace_root / "repeat-a"
    second = workspace_root / "repeat-b"
    assert (first / "build-plan.json").read_bytes() == (second / "build-plan.json").read_bytes()
    for sample_id in ("adapt-001", "adapt-002", "heldout-001"):
        assert (first / "samples" / f"{sample_id}.wav").read_bytes() == (second / "samples" / f"{sample_id}.wav").read_bytes()


def test_manifest_digest_mismatch_leaves_no_workspace(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    build_intake(intake_root)
    workspace_root = tmp_path / "workspaces"

    with pytest.raises(IntakeError, match="manifest_digest_mismatch"):
        prepare(intake_root, "a" * 64, workspace_root)

    assert list(workspace_root.iterdir()) == []


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    intake, _ = build_intake(intake_root)
    target = intake / "adapt-001.wav"
    target.rename(intake / "real.wav")
    target.symlink_to("real.wav")
    manifest = intake / "manifest.json"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    with pytest.raises(IntakeError, match="input_open_rejected"):
        prepare(intake_root, digest, tmp_path / "workspaces")


def test_world_readable_input_is_rejected(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    intake, digest = build_intake(intake_root)
    (intake / "adapt-001.txt").chmod(0o604)

    with pytest.raises(IntakeError, match="input_mode_invalid"):
        prepare(intake_root, digest, tmp_path / "workspaces")


def test_traversal_path_is_rejected_before_open(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    intake, _ = build_intake(intake_root)
    manifest_path = intake / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"][0]["audio_path"] = "../outside.wav"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(IntakeError, match="manifest_path_invalid"):
        prepare(intake_root, digest, tmp_path / "workspaces")


def test_empty_transcript_is_rejected(tmp_path: Path) -> None:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(mode=0o700)
    intake, digest = build_intake(intake_root)
    (intake / "adapt-001.txt").write_text("   ", encoding="utf-8")
    (intake / "adapt-001.txt").chmod(0o600)
    with pytest.raises(IntakeError, match="transcript_invalid"):
        prepare(intake_root, digest, tmp_path / "workspaces")


def test_source_identity_change_during_copy_is_rejected(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"immutable")
    source.chmod(0o600)
    descriptor = os.open(source, os.O_RDONLY)
    real_fstat = os.fstat
    calls = 0

    def changed_after_copy(fd):
        nonlocal calls
        metadata = real_fstat(fd)
        calls += 1
        if calls < 2:
            return metadata
        values = list(metadata)
        values[8] = metadata.st_mtime + 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", changed_after_copy)
    try:
        with pytest.raises(IntakeError, match="input_changed_during_copy"):
            _copy_fd(descriptor, tmp_path / "copy.bin", os.getuid(), 1024)
    finally:
        os.close(descriptor)
