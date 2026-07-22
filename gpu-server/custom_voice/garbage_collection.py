"""Queued, reference-aware custom-voice artifact deletion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from .registry import RegistryError, _save_registry, load_registry


class DeletionError(ValueError):
    """Safe deletion planning or verification failure."""


def _request_id(voice_id: str, version: str, digest: str) -> str:
    return hashlib.sha256(f"{voice_id}:{version}:{digest}".encode()).hexdigest()[:32]


def request_deletion(
    *,
    registry_path: Path,
    queue_root: Path,
    stable_voice_id: str,
    version: str,
    expected_artifact_sha256: str,
    targets: dict[str, Path],
    external_references: set[str] | frozenset[str] = frozenset(),
) -> dict[str, object]:
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][stable_voice_id]
        entry = voice["versions"][version]
    except KeyError as error:
        raise DeletionError("registry_version_missing") from error
    if entry["artifact_sha256"] != expected_artifact_sha256:
        raise DeletionError("artifact_digest_mismatch")
    if voice.get("active_version") == version or entry["state"] == "active":
        raise DeletionError("active_artifact_deletion_forbidden")
    if entry.get("rollback_retained", True):
        raise DeletionError("rollback_artifact_deletion_forbidden")
    reference = f"{stable_voice_id}:{version}:{expected_artifact_sha256}"
    if reference in external_references:
        raise DeletionError("artifact_still_referenced")
    allowed_categories = {"workspace", "cache", "previews", "artifact", "backup"}
    if not targets or set(targets) - allowed_categories:
        raise DeletionError("deletion_targets_invalid")
    request = {
        "schema_version": "custom-voice-deletion.v1",
        "request_id": _request_id(stable_voice_id, version, expected_artifact_sha256),
        "stable_voice_id": stable_voice_id,
        "version": version,
        "artifact_sha256": expected_artifact_sha256,
        "state": "queued",
        "targets": {category: str(path) for category, path in sorted(targets.items())},
    }
    queue_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    queue_root.chmod(0o700)
    path = queue_root / f"{request['request_id']}.json"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise DeletionError("deletion_already_requested") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        json.dump(request, destination, sort_keys=True, separators=(",", ":"))
        destination.flush()
        os.fsync(destination.fileno())
    return request


def _remove_confined(target: Path, root: Path) -> None:
    target_absolute = target.absolute()
    root_absolute = root.absolute()
    if target_absolute == root_absolute or not target_absolute.is_relative_to(root_absolute):
        raise DeletionError("deletion_target_unconfined")
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(target)
    else:
        target.unlink()
    if target.exists() or target.is_symlink():
        raise DeletionError("deletion_verification_failed")


def execute_deletion(
    *,
    registry_path: Path,
    queue_root: Path,
    request_id: str,
    allowed_roots: dict[str, Path],
) -> dict[str, object]:
    request_path = queue_root / f"{request_id}.json"
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeletionError("deletion_request_invalid") from error
    if request.get("request_id") != request_id or request.get("state") != "queued":
        raise DeletionError("deletion_request_invalid")
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][request["stable_voice_id"]]
        entry = voice["versions"][request["version"]]
    except KeyError as error:
        raise DeletionError("registry_version_missing") from error
    if voice.get("active_version") == request["version"] or entry.get("rollback_retained", True):
        raise DeletionError("deletion_reference_reappeared")
    if entry["artifact_sha256"] != request["artifact_sha256"]:
        raise DeletionError("artifact_digest_mismatch")
    for category, raw_path in request["targets"].items():
        root = allowed_roots.get(category)
        if root is None:
            raise DeletionError("deletion_root_missing")
        _remove_confined(Path(raw_path), root)
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][request["stable_voice_id"]]
        entry = voice["versions"][request["version"]]
    except KeyError as error:
        raise DeletionError("registry_version_missing") from error
    if voice.get("active_version") == request["version"] or entry.get("rollback_retained", True):
        raise DeletionError("deletion_reference_reappeared")
    if entry["artifact_sha256"] != request["artifact_sha256"]:
        raise DeletionError("artifact_digest_mismatch")
    entry["state"] = "deleted"
    _save_registry(registry_path, registry)
    request["state"] = "verified_deleted"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".deletion-", dir=queue_root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            json.dump(request, destination, sort_keys=True, separators=(",", ":"))
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, request_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {"request_id": request_id, "state": request["state"]}
