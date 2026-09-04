"""Deterministic, content-free source-audio quality checks."""

from __future__ import annotations

import array
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class ClippingPolicy:
    """Versioned PCM16 clipping thresholds used before normalization."""

    version: str = "pcm16-clipping.v1"
    near_ceiling_lsb: int = 1
    reject_consecutive: int = 3
    reject_fraction: float = 0.001

    def __post_init__(self) -> None:
        if not 0 <= self.near_ceiling_lsb < 32768:
            raise ValueError("near_ceiling_lsb must be between 0 and 32767")
        if self.reject_consecutive < 1:
            raise ValueError("reject_consecutive must be positive")
        if not 0 < self.reject_fraction <= 1:
            raise ValueError("reject_fraction must be in (0, 1]")


@dataclass(frozen=True)
class ClippingReport:
    sample_id: str
    policy_version: str
    outcome: Literal["pass", "review", "reject"]
    reason_codes: tuple[str, ...]
    peak_dbfs: float
    full_scale_samples: int
    near_ceiling_samples: int
    near_ceiling_fraction: float
    longest_near_ceiling_run: int


def analyze_pcm16_wav(
    audio_path: str | Path,
    *,
    sample_id: str,
    policy: ClippingPolicy = ClippingPolicy(),
) -> ClippingReport:
    """Classify clipping without returning paths or source audio content."""

    with wave.open(str(audio_path), "rb") as source:
        if source.getcomptype() != "NONE" or source.getsampwidth() != 2:
            raise ValueError("audio_format_unsupported")
        channels = source.getnchannels()
        frames = source.getnframes()
        raw_samples = source.readframes(frames)

    samples = array.array("h")
    samples.frombytes(raw_samples)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples or channels < 1:
        raise ValueError("audio_empty")

    positive_threshold = 32767 - policy.near_ceiling_lsb
    negative_threshold = -32768 + policy.near_ceiling_lsb
    full_scale_samples = 0
    near_ceiling_samples = 0
    longest_run = 0
    current_run = 0
    current_sign = 0
    peak = 0

    for sample in samples:
        peak = max(peak, abs(sample))
        if sample in (-32768, 32767):
            full_scale_samples += 1
        sign = 1 if sample >= positive_threshold else (-1 if sample <= negative_threshold else 0)
        if sign:
            near_ceiling_samples += 1
            current_run = current_run + 1 if sign == current_sign else 1
            current_sign = sign
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
            current_sign = 0

    near_fraction = near_ceiling_samples / len(samples)
    reasons: list[str] = []
    if longest_run >= policy.reject_consecutive:
        reasons.append("audio_clipping_sustained")
    if near_fraction >= policy.reject_fraction:
        reasons.append("audio_clipping_ratio")

    if reasons:
        outcome: Literal["pass", "review", "reject"] = "reject"
    elif full_scale_samples:
        outcome = "review"
        reasons.append("audio_peak_at_full_scale")
    else:
        outcome = "pass"

    peak_dbfs = 20 * math.log10(peak / 32768) if peak else float("-inf")
    return ClippingReport(
        sample_id=sample_id,
        policy_version=policy.version,
        outcome=outcome,
        reason_codes=tuple(reasons),
        peak_dbfs=peak_dbfs,
        full_scale_samples=full_scale_samples,
        near_ceiling_samples=near_ceiling_samples,
        near_ceiling_fraction=near_fraction,
        longest_near_ceiling_run=longest_run,
    )
