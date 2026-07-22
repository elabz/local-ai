import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.evaluator import KOKORO_CONFIG, KOKORO_MODEL, summarize, word_error_rate


def test_word_error_rate_normalizes_case_and_punctuation() -> None:
    assert word_error_rate("Hello, clear world!", "hello clear world") == 0.0
    assert word_error_rate("one two three four", "one two four") == 0.25


def test_summary_keeps_release_pending_for_human_review() -> None:
    summary = summarize(
        [
            {"word_error_rate": 0.0, "speaker_similarity": 0.72},
            {"word_error_rate": 0.1, "speaker_similarity": 0.68},
        ],
        max_wer=0.2,
        min_similarity=0.65,
    )
    assert summary["objective_outcome"] == "pass"
    assert summary["human_naturalness_outcome"] == "pending"
    assert summary["release_outcome"] == "pending_human_review"


def test_summary_rejects_failed_objective_threshold() -> None:
    summary = summarize(
        [{"word_error_rate": 0.4, "speaker_similarity": 0.8}],
        max_wer=0.2,
        min_similarity=0.65,
    )
    assert summary["objective_outcome"] == "reject"
    assert summary["release_outcome"] == "reject"


def test_empty_reference_is_rejected() -> None:
    with pytest.raises(ValueError, match="evaluation_reference_empty"):
        word_error_rate("", "anything")


def test_evaluator_uses_pinned_local_runtime_model() -> None:
    assert KOKORO_CONFIG == Path("/app/api/src/models/v1_0/config.json")
    assert KOKORO_MODEL == Path("/app/api/src/models/v1_0/kokoro-v1_0.pth")
    source = (Path(__file__).resolve().parents[1] / "custom_voice" / "evaluator.py").read_text()
    assert 'repo_id="hexgrad/Kokoro-82M"' in source
    assert "config=str(KOKORO_CONFIG)" in source
    assert "model=str(KOKORO_MODEL)" in source
    assert "evaluation_synthesis_failed" in source
    assert "evaluation_reference_preprocess_failed" in source
    assert 'sf.read(audio_path, dtype="float32", always_2d=False)' in source
    assert "evaluation_reference_embedding_failed" in source
    assert "evaluation_generated_preprocess_failed" in source
    assert "evaluation_generated_embedding_failed" in source
    assert "evaluation_preview_write_failed" in source
    assert "evaluation_asr_failed" in source
