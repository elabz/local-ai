import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.audio_quality import ClippingPolicy, analyze_pcm16_wav


def write_pcm16(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_audio_with_headroom_passes(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_pcm16(audio, [0, 1_000, -12_000, 20_000])
    report = analyze_pcm16_wav(audio, sample_id="adapt-001")
    assert report.outcome == "pass"
    assert report.reason_codes == ()


def test_isolated_full_scale_sample_requires_review(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_pcm16(audio, [0] * 2_000 + [32_767] + [0] * 2_000)
    report = analyze_pcm16_wav(audio, sample_id="adapt-001")
    assert report.outcome == "review"
    assert report.reason_codes == ("audio_peak_at_full_scale",)
    assert report.full_scale_samples == 1
    assert report.longest_near_ceiling_run == 1


def test_sustained_same_sign_ceiling_is_rejected(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_pcm16(audio, [0, 32_766, 32_767, 32_766, 0])
    report = analyze_pcm16_wav(audio, sample_id="adapt-001")
    assert report.outcome == "reject"
    assert "audio_clipping_sustained" in report.reason_codes


def test_opposite_ceiling_signs_are_not_one_flat_top(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_pcm16(audio, [0] * 2_000 + [32_767, -32_768] + [0] * 2_000)
    report = analyze_pcm16_wav(audio, sample_id="adapt-001")
    assert report.outcome == "review"
    assert report.longest_near_ceiling_run == 1


def test_near_ceiling_ratio_is_rejected(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_pcm16(audio, [32_766, 0] * 500)
    report = analyze_pcm16_wav(audio, sample_id="adapt-001")
    assert report.outcome == "reject"
    assert "audio_clipping_ratio" in report.reason_codes


def test_policy_validation() -> None:
    with pytest.raises(ValueError):
        ClippingPolicy(reject_fraction=0)
