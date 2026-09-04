"""Immutable custom-voice artifact sealing and provenance manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VOICE_ID_RE = re.compile(r"^custom-[a-z0-9](?:[a-z0-9-]{0,41}[a-z0-9])?$")
VERSION_RE = re.compile(r"^v[1-9][0-9]{0,8}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class ArtifactError(ValueError):
    """A safe artifact-sealing failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_private_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ArtifactError("artifact_input_missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ArtifactError("artifact_input_invalid")
    if metadata.st_mode & 0o077:
        raise ArtifactError("artifact_input_permissions_invalid")
    return metadata


def _exclusive_json(path: Path, value: dict[str, object]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ArtifactError("artifact_version_exists") from error
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(payload)
        destination.flush()
        os.fsync(destination.fileno())


def _validate_build_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict) or result.get("schema_version") != "custom-voice-build-result.v1":
        raise ArtifactError("build_result_invalid")
    for field in ("artifact_sha256", "build_plan_sha256", "manifest_sha256", "worker_image_digest"):
        if not SHA256_RE.fullmatch(str(result.get(field, ""))):
            raise ArtifactError("build_result_invalid")
    if result.get("builder_profile") != "kvoicewalk-multireference.v1" or not REVISION_RE.fullmatch(str(result.get("builder_revision", ""))):
        raise ArtifactError("build_result_invalid")
    if not isinstance(result.get("seed"), int) or not isinstance(result.get("artifact_size"), int) or result["artifact_size"] <= 0:
        raise ArtifactError("build_result_invalid")
    if not isinstance(result.get("steps"), int) or result["steps"] <= 0 or not isinstance(result.get("duration_seconds"), (int, float)) or result["duration_seconds"] <= 0:
        raise ArtifactError("build_result_invalid")
    runtime = result.get("kokoro_runtime_image")
    if not isinstance(runtime, str) or "@sha256:" not in runtime:
        raise ArtifactError("build_result_invalid")
    observations = result.get("resource_observations")
    required_observations = {
        "peak_observed_gpu_used_mib": int,
        "minimum_observed_gpu_free_mib": int,
        "peak_worker_rss_mib": (int, float),
        "peak_private_job_bytes": int,
    }
    if not isinstance(observations, dict):
        raise ArtifactError("build_result_resource_evidence_missing")
    for field, expected_type in required_observations.items():
        value = observations.get(field)
        if not isinstance(value, expected_type) or value < 0:
            raise ArtifactError("build_result_resource_evidence_invalid")
    return result


def seal_artifact(
    *,
    artifact: Path,
    build_result: Path,
    store: Path,
    stable_voice_id: str,
    version: str,
    language: str,
) -> dict[str, object]:
    """Copy one internally built tensor into an immutable version directory."""

    if not VOICE_ID_RE.fullmatch(stable_voice_id):
        raise ArtifactError("stable_voice_id_invalid")
    if not VERSION_RE.fullmatch(version):
        raise ArtifactError("artifact_version_invalid")
    if language not in {"a", "b"}:
        raise ArtifactError("artifact_language_invalid")
    artifact_metadata = _regular_private_file(artifact)
    _regular_private_file(build_result)
    try:
        result = _validate_build_result(json.loads(build_result.read_text(encoding="utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError("build_result_invalid") from error
    artifact_digest = sha256_file(artifact)
    if result["artifact_sha256"] != artifact_digest or result.get("artifact_size") != artifact_metadata.st_size:
        raise ArtifactError("artifact_result_mismatch")

    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(store, 0o700)
    version_root = store / stable_voice_id / version
    version_root.parent.mkdir(mode=0o700, exist_ok=True)
    if version_root.exists():
        raise ArtifactError("artifact_version_exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=version_root.parent))
    os.chmod(temporary, 0o700)
    try:
        sealed_artifact = temporary / f"{artifact_digest}.pt"
        shutil.copyfile(artifact, sealed_artifact)
        os.chmod(sealed_artifact, 0o600)
        if sha256_file(sealed_artifact) != artifact_digest:
            raise ArtifactError("artifact_copy_mismatch")
        result_digest = sha256_file(build_result)
        manifest: dict[str, object] = {
            "schema_version": "custom-voice-artifact.v1",
            "stable_voice_id": stable_voice_id,
            "version": version,
            "language": language,
            "artifact": {
                "sha256": artifact_digest,
                "size": artifact_metadata.st_size,
                "serialization": "pytorch-weights-only-tensor",
            },
            "compatibility": {
                "kokoro_runtime_image": result["kokoro_runtime_image"],
                "voice_pack_contract": "kokoro-v1-float32-style-tensor.v1",
            },
            "provenance": {
                "build_result_sha256": result_digest,
                "build_plan_sha256": result["build_plan_sha256"],
                "source_manifest_sha256": result["manifest_sha256"],
                "builder_profile": result["builder_profile"],
                "builder_revision": result["builder_revision"],
                "worker_image_digest": result["worker_image_digest"],
                "seed": result["seed"],
                "steps": result["steps"],
                "duration_seconds": result["duration_seconds"],
                "resource_observations": result["resource_observations"],
            },
        }
        _exclusive_json(temporary / "manifest.json", manifest)
        os.replace(temporary, version_root)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--build-result", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--stable-voice-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--language", required=True)
    arguments = parser.parse_args()
    try:
        manifest = seal_artifact(
            artifact=arguments.artifact,
            build_result=arguments.build_result,
            store=arguments.store,
            stable_voice_id=arguments.stable_voice_id,
            version=arguments.version,
            language=arguments.language,
        )
        print(json.dumps({
            "outcome": "succeeded",
            "stable_voice_id": manifest["stable_voice_id"],
            "version": manifest["version"],
            "artifact_sha256": manifest["artifact"]["sha256"],
        }, sort_keys=True, separators=(",", ":")))
    except ArtifactError as error:
        print(json.dumps({"outcome": "failed", "reason": str(error)}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
