"""Pinned Kokoro artifact compatibility runner entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FIXED_PHRASES = (
    "The quick amber fox crosses the quiet valley at sunrise.",
    "Clear speech should remain stable across this second sentence.",
)
KOKORO_CONFIG = Path("/app/api/src/models/v1_0/config.json")
KOKORO_MODEL = Path("/app/api/src/models/v1_0/kokoro-v1_0.pth")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_tensor(tensor, torch_module) -> None:
    if not torch_module.is_tensor(tensor):
        raise ValueError("artifact_not_tensor")
    if tensor.dtype != torch_module.float32:
        raise ValueError("artifact_dtype_invalid")
    if tensor.ndim != 3 or tensor.shape[-2:] != (1, 256) or tensor.shape[0] < 1:
        raise ValueError("artifact_shape_invalid")
    if not bool(torch_module.isfinite(tensor).all()):
        raise ValueError("artifact_non_finite")


def validate_audio(audio, numpy_module) -> int:
    values = numpy_module.asarray(audio)
    if values.size == 0:
        raise ValueError("synthesis_empty")
    if values.ndim != 1:
        raise ValueError("synthesis_channels_invalid")
    if not bool(numpy_module.isfinite(values).all()):
        raise ValueError("synthesis_non_finite")
    if float(numpy_module.max(numpy_module.abs(values))) > 1.0:
        raise ValueError("synthesis_range_invalid")
    return int(values.size)


def run(artifact: Path, expected_sha256: str, language: str) -> dict[str, object]:
    import numpy as np
    import torch
    from kokoro import KModel, KPipeline

    if not SHA256_RE.fullmatch(expected_sha256):
        raise ValueError("artifact_digest_invalid")
    if sha256_file(artifact) != expected_sha256:
        raise ValueError("artifact_digest_mismatch")

    tensor = torch.load(artifact, map_location="cpu", weights_only=True)
    validate_tensor(tensor, torch)
    if not KOKORO_CONFIG.is_file() or not KOKORO_MODEL.is_file():
        raise ValueError("runtime_model_missing")
    model = KModel(
        repo_id="hexgrad/Kokoro-82M",
        config=str(KOKORO_CONFIG),
        model=str(KOKORO_MODEL),
    ).to("cpu").eval()
    pipeline = KPipeline(
        lang_code=language,
        repo_id="hexgrad/Kokoro-82M",
        model=model,
        device="cpu",
    )
    frame_counts: list[int] = []
    for phrase in FIXED_PHRASES:
        chunks = [audio for _, _, audio in pipeline(phrase, voice=tensor)]
        if not chunks:
            raise ValueError("synthesis_empty")
        frame_counts.append(validate_audio(np.concatenate(chunks), np))
    return {
        "outcome": "pass",
        "artifact_sha256": expected_sha256,
        "phrase_count": len(FIXED_PHRASES),
        "frame_counts": frame_counts,
        "sample_rate_hz": 24_000,
        "runtime_image": os.environ.get("COMPAT_RUNTIME_IMAGE", "unknown"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--language", default="a")
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.artifact, arguments.sha256, arguments.language), sort_keys=True))
    except Exception as error:
        code = str(error) if str(error).replace("_", "").isalnum() else "compatibility_failed"
        print(json.dumps({"outcome": "reject", "reason": code}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
