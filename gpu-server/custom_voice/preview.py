"""Protected custom-voice preview staging and digest-verified reads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .registry import discover_active, stage_version

PREVIEW_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PreviewError(ValueError):
    """Safe preview or staging failure."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_protected_preview(
    *,
    preview_root: Path,
    preview_id: str,
    expected_sha256: str,
    scopes: set[str] | frozenset[str],
) -> bytes:
    if "custom_voice.preview.read" not in scopes:
        raise PreviewError("preview_forbidden")
    if not PREVIEW_ID_RE.fullmatch(preview_id) or not SHA256_RE.fullmatch(expected_sha256):
        raise PreviewError("preview_reference_invalid")
    root_descriptor = file_descriptor = -1
    try:
        root_descriptor = os.open(preview_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_descriptor = os.open(f"{preview_id}.wav", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise PreviewError("preview_file_invalid")
        with os.fdopen(os.dup(file_descriptor), "rb") as source:
            content = source.read(64 * 1024 * 1024 + 1)
        if len(content) > 64 * 1024 * 1024:
            raise PreviewError("preview_too_large")
        if _sha256_bytes(content) != expected_sha256:
            raise PreviewError("preview_digest_mismatch")
        return content
    except OSError as error:
        raise PreviewError("preview_unavailable") from error
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)


def stage_for_review(
    *,
    registry_path: Path,
    artifact_manifest_path: Path,
    evaluation_path: Path,
    compatibility_path: Path,
    built_in_voice_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, object]:
    try:
        manifest_bytes = artifact_manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        compatibility = json.loads(compatibility_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreviewError("staging_evidence_invalid") from error
    artifact = manifest.get("artifact", {})
    artifact_digest = artifact.get("sha256")
    if evaluation.get("artifact_sha256") != artifact_digest or compatibility.get("artifact_sha256") != artifact_digest:
        raise PreviewError("staging_digest_mismatch")
    if compatibility.get("outcome") != "pass":
        raise PreviewError("staging_compatibility_failed")
    if evaluation.get("objective_outcome") not in {"pass", "reject"}:
        raise PreviewError("staging_evaluation_incomplete")
    entry = stage_version(
        registry_path=registry_path,
        stable_voice_id=str(manifest.get("stable_voice_id", "")),
        version=str(manifest.get("version", "")),
        artifact_sha256=str(artifact_digest),
        artifact_manifest_sha256=_sha256_bytes(manifest_bytes),
        language=str(manifest.get("language", "")),
        built_in_voice_ids=built_in_voice_ids,
    )
    if manifest["stable_voice_id"] in discover_active(registry_path):
        raise PreviewError("staging_published_unexpectedly")
    return {
        "stable_voice_id": manifest["stable_voice_id"],
        "version": manifest["version"],
        "state": entry["state"],
        "objective_outcome": evaluation["objective_outcome"],
        "human_naturalness_outcome": evaluation.get("human_naturalness_outcome", "pending"),
        "previews": [
            {"preview_id": sample["preview_id"], "sha256": sample["preview_sha256"]}
            for sample in evaluation.get("samples", [])
        ],
    }
