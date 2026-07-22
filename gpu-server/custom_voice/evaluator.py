"""Held-out evaluation for internally produced Kokoro voice packs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import wave
from pathlib import Path, PurePosixPath

WORD_RE = re.compile(r"[a-z0-9']+")
KOKORO_CONFIG = Path("/app/api/src/models/v1_0/config.json")
KOKORO_MODEL = Path("/app/api/src/models/v1_0/kokoro-v1_0.pth")


def normalized_words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected = normalized_words(reference)
    actual = normalized_words(hypothesis)
    if not expected:
        raise ValueError("evaluation_reference_empty")
    previous = list(range(len(actual) + 1))
    for index, expected_word in enumerate(expected, start=1):
        current = [index]
        for position, actual_word in enumerate(actual, start=1):
            current.append(min(
                current[-1] + 1,
                previous[position] + 1,
                previous[position - 1] + (expected_word != actual_word),
            ))
        previous = current
    return previous[-1] / len(expected)


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("evaluation_path_invalid")
    return Path(*candidate.parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wav_bytes(audio, numpy_module) -> bytes:
    values = numpy_module.asarray(audio, dtype=numpy_module.float32)
    if values.ndim != 1 or values.size == 0 or not bool(numpy_module.isfinite(values).all()):
        raise ValueError("evaluation_audio_invalid")
    pcm = (numpy_module.clip(values, -1.0, 1.0) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(24_000)
        destination.writeframes(pcm.tobytes())
    return output.getvalue()


def summarize(sample_results: list[dict[str, object]], *, max_wer: float, min_similarity: float) -> dict[str, object]:
    if not sample_results:
        raise ValueError("heldout_samples_missing")
    mean_wer = sum(float(item["word_error_rate"]) for item in sample_results) / len(sample_results)
    mean_similarity = sum(float(item["speaker_similarity"]) for item in sample_results) / len(sample_results)
    objective_pass = mean_wer <= max_wer and mean_similarity >= min_similarity
    return {
        "mean_word_error_rate": mean_wer,
        "mean_speaker_similarity": mean_similarity,
        "thresholds": {"max_mean_word_error_rate": max_wer, "min_mean_speaker_similarity": min_similarity},
        "objective_outcome": "pass" if objective_pass else "reject",
        "human_naturalness_outcome": "pending",
        "release_outcome": "pending_human_review" if objective_pass else "reject",
    }


def evaluate(
    *,
    artifact: Path,
    expected_sha256: str,
    plan_path: Path,
    workspace: Path,
    preview_root: Path,
    asr_url: str,
    max_wer: float,
    min_similarity: float,
) -> dict[str, object]:
    import httpx
    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline
    from resemblyzer import VoiceEncoder, preprocess_wav

    if _sha256(artifact) != expected_sha256:
        raise ValueError("artifact_digest_mismatch")
    voice = torch.load(artifact, map_location="cpu", weights_only=True)
    if not torch.is_tensor(voice) or voice.dtype != torch.float32 or not bool(torch.isfinite(voice).all()):
        raise ValueError("artifact_invalid")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    heldouts = [sample for sample in plan.get("samples", []) if sample.get("role") == "heldout"]
    if len(heldouts) != 4:
        raise ValueError("heldout_samples_invalid")

    preview_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    preview_root.chmod(0o700)
    if not KOKORO_CONFIG.is_file() or not KOKORO_MODEL.is_file():
        raise ValueError("runtime_model_missing")
    model = KModel(
        repo_id="hexgrad/Kokoro-82M",
        config=str(KOKORO_CONFIG),
        model=str(KOKORO_MODEL),
    ).to("cuda").eval()
    pipeline = KPipeline(
        lang_code="a",
        repo_id="hexgrad/Kokoro-82M",
        model=model,
        device="cuda",
    )
    encoder = VoiceEncoder(device="cuda")
    results: list[dict[str, object]] = []
    for sample in heldouts:
        sample_id = str(sample["sample_id"])
        audio_path = workspace / _safe_relative(str(sample["audio_path"]))
        transcript_path = workspace / _safe_relative(str(sample["transcript_path"]))
        transcript = transcript_path.read_text(encoding="utf-8").strip()
        try:
            chunks = [audio for _, _, audio in pipeline(transcript, voice=voice)]
        except Exception:
            raise ValueError("evaluation_synthesis_failed") from None
        if not chunks:
            raise ValueError("evaluation_synthesis_empty")
        generated = np.concatenate(chunks).astype(np.float32)
        try:
            reference_audio, reference_rate = sf.read(audio_path, dtype="float32", always_2d=False)
            if reference_rate != 24_000 or reference_audio.ndim != 1 or reference_audio.size == 0:
                raise ValueError("evaluation_reference_audio_invalid")
            reference_wav = preprocess_wav(reference_audio, source_sr=reference_rate)
        except Exception:
            raise ValueError("evaluation_reference_preprocess_failed") from None
        try:
            reference_embedding = encoder.embed_utterance(reference_wav)
        except Exception:
            raise ValueError("evaluation_reference_embedding_failed") from None
        try:
            generated_wav = preprocess_wav(generated, source_sr=24_000)
        except Exception:
            raise ValueError("evaluation_generated_preprocess_failed") from None
        try:
            generated_embedding = encoder.embed_utterance(generated_wav)
        except Exception:
            raise ValueError("evaluation_generated_embedding_failed") from None
        similarity = float(np.dot(reference_embedding, generated_embedding))
        preview_id = hashlib.sha256(f"{expected_sha256}:{sample_id}".encode()).hexdigest()[:32]
        preview_path = preview_root / f"{preview_id}.wav"
        try:
            sf.write(preview_path, generated, 24_000, subtype="PCM_16")
            preview_path.chmod(0o600)
        except Exception:
            raise ValueError("evaluation_preview_write_failed") from None
        try:
            response = httpx.post(
                asr_url,
                data={"model": "guillaumekln/faster-whisper-small.en", "response_format": "json"},
                files={"file": ("evaluation.wav", _wav_bytes(generated, np), "audio/wav")},
                timeout=120,
            )
            response.raise_for_status()
            hypothesis = str(response.json().get("text", ""))
        except Exception:
            raise ValueError("evaluation_asr_failed") from None
        results.append({
            "sample_id": sample_id,
            "word_error_rate": word_error_rate(transcript, hypothesis),
            "speaker_similarity": similarity,
            "preview_id": preview_id,
            "preview_sha256": _sha256(preview_path),
            "frames": int(generated.size),
        })
    summary = summarize(results, max_wer=max_wer, min_similarity=min_similarity)
    return {
        "schema_version": "custom-voice-evaluation.v1",
        "artifact_sha256": expected_sha256,
        "heldout_count": len(results),
        "samples": results,
        **summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--preview-root", type=Path, required=True)
    parser.add_argument("--asr-url", required=True)
    parser.add_argument("--max-wer", type=float, default=0.20)
    parser.add_argument("--min-similarity", type=float, default=0.65)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = evaluate(
            artifact=arguments.artifact,
            expected_sha256=arguments.sha256,
            plan_path=arguments.plan,
            workspace=arguments.workspace,
            preview_root=arguments.preview_root,
            asr_url=arguments.asr_url,
            max_wer=arguments.max_wer,
            min_similarity=arguments.min_similarity,
        )
        arguments.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        arguments.output.chmod(0o600)
        print(json.dumps({"outcome": result["objective_outcome"], "heldout_count": result["heldout_count"]}))
    except Exception as error:
        code = str(error) if str(error).replace("_", "").isalnum() else "evaluation_failed"
        print(json.dumps({"outcome": "failed", "reason": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
