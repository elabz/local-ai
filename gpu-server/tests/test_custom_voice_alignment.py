import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.alignment import classify_alignment


def test_exact_presegmented_transcript_passes() -> None:
    result = classify_alignment("adapt-001", "The exact transcript.", "the exact transcript", 0.20)
    assert result == {
        "sample_id": "adapt-001",
        "word_error_rate": 0.0,
        "outcome": "pass",
        "reason": None,
    }


def test_material_alignment_error_is_rejected_without_content() -> None:
    result = classify_alignment("heldout-001", "one two three four", "one four", 0.20)
    assert result["outcome"] == "reject"
    assert result["reason"] == "transcript_alignment_failed"
    assert "one" not in str(result)


def test_invalid_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="alignment_threshold_invalid"):
        classify_alignment("adapt-001", "words", "words", 1.1)
