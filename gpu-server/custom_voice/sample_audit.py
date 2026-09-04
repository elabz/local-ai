"""Content-free acoustic and speaker-consistency audit for a private build plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath


def safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("sample_path_invalid")
    return Path(*candidate.parts)


def audit(plan_path: Path, workspace: Path, *, device: str = "cpu") -> dict[str, object]:
    import numpy as np
    import soundfile as sf
    from resemblyzer import VoiceEncoder, preprocess_wav

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    samples = plan.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise ValueError("samples_invalid")
    encoder = VoiceEncoder(device=device)
    rows: list[dict[str, object]] = []
    embeddings = []
    for sample in samples:
        audio_path = workspace / safe_relative(str(sample["audio_path"]))
        try:
            audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
        except Exception:
            raise ValueError("sample_audio_read_failed") from None
        if audio.ndim != 1 or audio.size == 0:
            raise ValueError("sample_audio_invalid")
        try:
            waveform = preprocess_wav(audio, source_sr=sample_rate)
        except Exception:
            raise ValueError("sample_preprocess_failed") from None
        try:
            embedding = encoder.embed_utterance(waveform)
        except Exception:
            raise ValueError("sample_embedding_failed") from None
        norm = np.linalg.norm(embedding)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("sample_embedding_invalid")
        embeddings.append(embedding / norm)
        rows.append({
            "sample_id": str(sample["sample_id"]),
            "role": str(sample["role"]),
            "duration_seconds": round(float(audio.size / sample_rate), 2),
            "peak": round(float(np.max(np.abs(audio))), 4),
            "rms": round(float(np.sqrt(np.mean(audio * audio))), 4),
        })
    matrix = np.stack(embeddings) @ np.stack(embeddings).T
    for index, row in enumerate(rows):
        other = np.delete(matrix[index], index)
        row["mean_similarity_to_others"] = round(float(np.mean(other)), 4)
        row["min_similarity_to_other"] = round(float(np.min(other)), 4)
    pairwise = matrix[~np.eye(len(rows), dtype=bool)]
    return {
        "schema_version": "custom-voice-sample-audit.v1",
        "sample_count": len(rows),
        "overall_pairwise_mean": round(float(np.mean(pairwise)), 4),
        "overall_pairwise_min": round(float(np.min(pairwise)), 4),
        "samples": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    arguments = parser.parse_args()
    try:
        print(json.dumps(audit(arguments.plan, arguments.workspace, device=arguments.device), sort_keys=True))
    except Exception as error:
        code = str(error) if str(error).replace("_", "").isalnum() else "sample_audit_failed"
        print(json.dumps({"outcome": "failed", "reason": code, "error_type": type(error).__name__}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
