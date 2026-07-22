"""ASR-grade transcript alignment for the presegmented pilot profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath

try:
    from .evaluator import word_error_rate
except ImportError:  # Direct container entry point.
    from evaluator import word_error_rate


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("alignment_path_invalid")
    return Path(*candidate.parts)


def classify_alignment(sample_id: str, reference: str, hypothesis: str, max_wer: float) -> dict[str, object]:
    if not 0 <= max_wer <= 1:
        raise ValueError("alignment_threshold_invalid")
    wer = word_error_rate(reference, hypothesis)
    return {
        "sample_id": sample_id,
        "word_error_rate": wer,
        "outcome": "pass" if wer <= max_wer else "reject",
        "reason": None if wer <= max_wer else "transcript_alignment_failed",
    }


def align_workspace(
    *,
    plan_path: Path,
    workspace: Path,
    asr_url: str,
    max_wer: float = 0.20,
) -> dict[str, object]:
    import httpx

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    samples = plan.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("alignment_samples_invalid")
    findings: list[dict[str, object]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id", ""))
        audio = workspace / _safe_relative(str(sample["audio_path"]))
        transcript = workspace / _safe_relative(str(sample["transcript_path"]))
        if not audio.is_file() or not transcript.is_file():
            raise ValueError("alignment_input_missing")
        reference = transcript.read_text(encoding="utf-8").strip()
        with audio.open("rb") as source:
            response = httpx.post(
                asr_url,
                data={"model": "guillaumekln/faster-whisper-small.en", "response_format": "json"},
                files={"file": ("sample.wav", source, "audio/wav")},
                timeout=120,
            )
        response.raise_for_status()
        hypothesis = str(response.json().get("text", ""))
        findings.append(classify_alignment(sample_id, reference, hypothesis, max_wer))
    rejected = sum(finding["outcome"] == "reject" for finding in findings)
    return {
        "schema_version": "custom-voice-alignment.v1",
        "profile": "presegmented-whisper-small-en.v1",
        "segmentation": "manifest_clip_boundaries",
        "max_word_error_rate": max_wer,
        "sample_count": len(findings),
        "rejected_count": rejected,
        "outcome": "pass" if rejected == 0 else "reject",
        "samples": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--asr-url", required=True)
    parser.add_argument("--max-wer", type=float, default=0.20)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = align_workspace(
            plan_path=arguments.plan,
            workspace=arguments.workspace,
            asr_url=arguments.asr_url,
            max_wer=arguments.max_wer,
        )
        arguments.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        arguments.output.chmod(0o600)
        print(json.dumps({"outcome": result["outcome"], "sample_count": result["sample_count"]}))
        if result["outcome"] != "pass":
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as error:
        code = str(error) if str(error).replace("_", "").isalnum() else "alignment_failed"
        print(json.dumps({"outcome": "failed", "reason": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
