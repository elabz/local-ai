import hashlib
import io
import json
import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.intake import IntakeProfile, prepare_workspace
from custom_voice.intake_pull import (
    IntakeConflict,
    IntakePullError,
    normalize_origins,
    pull_intake,
)

PROFILE = IntakeProfile(adaptation_count=2, heldout_count=1, min_duration_seconds=0.5, max_duration_seconds=2.0)
ORIGINS = normalize_origins(["http://heartcode.test:8000"])


def wav_bytes(rate: int = 16_000, channels: int = 1) -> bytes:
    samples = [int(2_000 * ((index % 20) - 10) / 10) for index in range(rate)]
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(struct.pack(f"<{len(samples)}h", *samples) * channels)
    return output.getvalue()


AUDIO = wav_bytes()


class FakeOrigin:
    def __init__(self, content=AUDIO, status=200):
        self.content, self.status, self.calls = content, status, []

    def __call__(self, url: str, max_bytes: int):
        self.calls.append(url)
        return self.status, self.content


def request(url_suffix: str = "a") -> dict:
    samples = []
    for sample_id, role in (("adapt-001", "adaptation"), ("adapt-002", "adaptation"), ("heldout-001", "heldout")):
        samples.append({
            "sample_id": sample_id,
            "role": role,
            "fetch_url": f"http://heartcode.test:8000/api/v1/internal/custom-voice-samples/{sample_id}?signature={url_suffix}",
            "audio_sha256": hashlib.sha256(AUDIO).hexdigest(),
            "transcript": "one two",
            "sample_rate_hz": 16_000,
            "channels": 1,
            "encoding": "pcm_s16le",
        })
    return {
        "schema_version": "custom-voice-intake-request.v1",
        "intake_id": "hc-0f1e2d3c",
        "stable_voice_id": "custom-test-voice",
        "version": "v1",
        "language": "en-US",
        "authorization_id": "hc-consent-test",
        "builder_profile": "kvoicewalk-multireference.v1",
        "samples": samples,
    }


def test_pulled_intake_is_consumed_by_the_real_workspace_preparation(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    result = pull_intake(request(), intake_root=root, allowed_origins=ORIGINS, fetch=FakeOrigin(), profile=PROFILE)
    assert result["sample_count"] == 3
    manifest_bytes = (root / "hc-0f1e2d3c" / "manifest.json").read_bytes()
    assert result["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert json.loads(manifest_bytes)["stable_voice_id"] == "custom-test-voice"
    prepared = prepare_workspace(
        intake_root=root,
        intake_id="hc-0f1e2d3c",
        expected_manifest_sha256=result["manifest_sha256"],
        workspace_root=tmp_path / "workspaces",
        job_id="cvj-test",
        seed=7,
        profile=PROFILE,
    )
    assert prepared["sample_count"] == 3


def test_retry_with_freshly_signed_urls_returns_the_same_intake_without_refetching(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    first = pull_intake(request("a"), intake_root=root, allowed_origins=ORIGINS, fetch=FakeOrigin(), profile=PROFILE)
    origin = FakeOrigin()
    second = pull_intake(request("b"), intake_root=root, allowed_origins=ORIGINS, fetch=origin, profile=PROFILE)
    assert second["manifest_sha256"] == first["manifest_sha256"]
    assert origin.calls == []


def test_same_intake_id_with_different_content_conflicts(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    pull_intake(request(), intake_root=root, allowed_origins=ORIGINS, fetch=FakeOrigin(), profile=PROFILE)
    changed = request()
    changed["samples"][0]["transcript"] = "three four"
    with pytest.raises(IntakeConflict):
        pull_intake(changed, intake_root=root, allowed_origins=ORIGINS, fetch=FakeOrigin(), profile=PROFILE)


@pytest.mark.parametrize(
    ("origin", "code"),
    [
        (FakeOrigin(status=302), "intake_fetch_redirect_refused"),
        (FakeOrigin(status=403), "intake_fetch_failed"),
        (FakeOrigin(content=AUDIO + b"x"), "audio_digest_mismatch"),
    ],
)
def test_fetch_failures_publish_nothing(tmp_path: Path, origin, code: str) -> None:
    root = tmp_path / "intake"
    with pytest.raises(IntakePullError, match=code):
        pull_intake(request(), intake_root=root, allowed_origins=ORIGINS, fetch=origin, profile=PROFILE)
    assert list(root.iterdir()) == []


def test_origin_outside_the_allow_list_is_never_fetched(tmp_path: Path) -> None:
    payload = request()
    payload["samples"][1]["fetch_url"] = "http://169.254.169.254:80/latest/meta-data"
    origin = FakeOrigin()
    with pytest.raises(IntakePullError, match="intake_origin_forbidden"):
        pull_intake(payload, intake_root=tmp_path, allowed_origins=ORIGINS, fetch=origin, profile=PROFILE)
    assert origin.calls == []


def test_declared_format_must_match_the_audio(tmp_path: Path) -> None:
    stereo = wav_bytes(channels=2)
    payload = request()
    for sample in payload["samples"]:
        sample["audio_sha256"] = hashlib.sha256(stereo).hexdigest()
    with pytest.raises(IntakePullError, match="intake_audio_format_mismatch"):
        pull_intake(payload, intake_root=tmp_path, allowed_origins=ORIGINS, fetch=FakeOrigin(stereo), profile=PROFILE)


def test_byte_cap_spans_the_whole_intake(tmp_path: Path) -> None:
    small = IntakeProfile(adaptation_count=2, heldout_count=1, max_total_bytes=len(AUDIO) * 2)
    with pytest.raises(IntakePullError, match="intake_sample_too_large"):
        pull_intake(request(), intake_root=tmp_path, allowed_origins=ORIGINS, fetch=FakeOrigin(), profile=small)


def test_profile_counts_and_ids_are_enforced_before_any_fetch(tmp_path: Path) -> None:
    payload = request()
    payload["samples"] = payload["samples"][:2]
    origin = FakeOrigin()
    with pytest.raises(IntakePullError, match="sample_count_invalid"):
        pull_intake(payload, intake_root=tmp_path, allowed_origins=ORIGINS, fetch=origin, profile=PROFILE)
    payload = request()
    payload["intake_id"] = "../escape"
    with pytest.raises(IntakePullError, match="intake_id_invalid"):
        pull_intake(payload, intake_root=tmp_path, allowed_origins=ORIGINS, fetch=origin, profile=PROFILE)
    assert origin.calls == []
