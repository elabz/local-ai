import hashlib
import json

from custom_voice.safe_plan_summary import summarize


def test_summary_is_content_free_and_allow_listed(tmp_path):
    path = tmp_path / "build-plan.json"
    payload = {
        "schema_version": "custom-voice-build-plan.v1",
        "job_id": "job-1",
        "seed": 137,
        "samples": [
            {"sample_id": "adapt-002", "role": "adaptation", "path": "private.wav"},
            {"sample_id": "heldout-001", "role": "heldout", "path": "secret.wav"},
        ],
        "references": [{"sample_id": "adapt-002"}],
        "transcript": "must not be emitted",
    }
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)

    result = summarize(path)

    assert result["plan_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["fields"]["job_id"] == "job-1"
    assert result["construction_ids"] == ["adapt-002"]
    assert result["heldout_reference_count"] == 0
    assert "transcript" not in str(result)
    assert "private.wav" not in str(result)
