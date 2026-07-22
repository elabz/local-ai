from pathlib import Path

import pytest

from custom_voice.sample_audit import safe_relative


@pytest.mark.parametrize("value", ("/absolute.wav", "../escape.wav", "audio/../escape.wav", ""))
def test_rejects_unsafe_sample_paths(value: str) -> None:
    with pytest.raises(ValueError, match="sample_path_invalid"):
        safe_relative(value)


def test_accepts_confined_sample_path() -> None:
    assert safe_relative("audio/adapt-001.wav") == Path("audio/adapt-001.wav")
