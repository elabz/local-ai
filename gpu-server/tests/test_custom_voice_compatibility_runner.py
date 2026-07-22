import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.compatibility_runner import KOKORO_CONFIG, KOKORO_MODEL, validate_audio, validate_tensor


def test_valid_voice_tensor_and_audio_pass() -> None:
    validate_tensor(torch.zeros((510, 1, 256), dtype=torch.float32), torch)
    assert validate_audio(np.zeros(24_000, dtype=np.float32), np) == 24_000


@pytest.mark.parametrize(
    "tensor,reason",
    [
        (torch.zeros((510, 256), dtype=torch.float32), "artifact_shape_invalid"),
        (torch.zeros((510, 1, 256), dtype=torch.float64), "artifact_dtype_invalid"),
        (torch.full((510, 1, 256), float("nan")), "artifact_non_finite"),
    ],
)
def test_invalid_voice_tensor_fails_closed(tensor, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        validate_tensor(tensor, torch)


@pytest.mark.parametrize(
    "audio,reason",
    [
        (np.array([], dtype=np.float32), "synthesis_empty"),
        (np.zeros((2, 10), dtype=np.float32), "synthesis_channels_invalid"),
        (np.array([np.nan], dtype=np.float32), "synthesis_non_finite"),
        (np.array([1.1], dtype=np.float32), "synthesis_range_invalid"),
    ],
)
def test_invalid_synthesis_fails_closed(audio, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        validate_audio(audio, np)


def test_compatibility_runner_uses_pinned_local_runtime_model() -> None:
    assert KOKORO_CONFIG == Path("/app/api/src/models/v1_0/config.json")
    assert KOKORO_MODEL == Path("/app/api/src/models/v1_0/kokoro-v1_0.pth")
    source = (Path(__file__).resolve().parents[1] / "custom_voice" / "compatibility_runner.py").read_text()
    assert 'repo_id="hexgrad/Kokoro-82M"' in source
    assert "config=str(KOKORO_CONFIG)" in source
    assert "model=str(KOKORO_MODEL)" in source
    dockerfile = (Path(__file__).resolve().parents[1] / "custom_voice" / "Dockerfile.compatibility").read_text()
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert "TRANSFORMERS_OFFLINE=1" in dockerfile
