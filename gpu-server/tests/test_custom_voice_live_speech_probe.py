import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.live_speech_probe import ProbeResult, percentile, summarize


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([0.4, 0.1, 0.3, 0.2], 0.95) == 0.4


def test_summary_passes_only_valid_opus_within_build_budget() -> None:
    result = summarize([
        ProbeResult("quick-chat", 0.50, 200, True),
        ProbeResult("character", 0.55, 200, True),
    ], baseline_p95_seconds=0.49)
    assert result["outcome"] == "pass"
    assert result["opus_40k_valid_count"] == 2
    assert result["workloads"] == {"character": 1, "quick-chat": 1}


@pytest.mark.parametrize("results", [
    [ProbeResult("quick-chat", 0.3, 500, False)],
    [ProbeResult("quick-chat", 0.7, 200, True)],
])
def test_summary_rejects_errors_or_latency_regression(results) -> None:
    assert summarize(results, baseline_p95_seconds=0.49)["outcome"] == "reject"
