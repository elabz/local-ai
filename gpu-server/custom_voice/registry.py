"""Atomic local registry for immutable custom-voice versions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VOICE_ID_RE = re.compile(r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERSION_RE = re.compile(r"^v[1-9][0-9]{0,8}$")
VERSION_STATES = {"staged", "active", "unhealthy", "retired", "deleted"}


class RegistryError(ValueError):
    """Safe registry validation or transition failure."""


def _empty_registry() -> dict[str, object]:
    return {"schema_version": "custom-voice-registry.v1", "voices": {}}


def load_registry(path: Path) -> dict[str, object]:
    if not path.exists():
        return _empty_registry()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryError("registry_invalid") from error
    if value.get("schema_version") != "custom-voice-registry.v1" or not isinstance(value.get("voices"), dict):
        raise RegistryError("registry_invalid")
    return value


def _save_registry(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".registry-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(value, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def stage_version(
    *,
    registry_path: Path,
    stable_voice_id: str,
    version: str,
    artifact_sha256: str,
    artifact_manifest_sha256: str,
    language: str,
    built_in_voice_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    if not VOICE_ID_RE.fullmatch(stable_voice_id) or stable_voice_id in built_in_voice_ids:
        raise RegistryError("stable_voice_id_invalid")
    if not VERSION_RE.fullmatch(version):
        raise RegistryError("artifact_version_invalid")
    if not SHA256_RE.fullmatch(artifact_sha256) or not SHA256_RE.fullmatch(artifact_manifest_sha256):
        raise RegistryError("artifact_digest_invalid")
    if language not in {"a", "b"}:
        raise RegistryError("artifact_language_invalid")
    registry = load_registry(registry_path)
    voices = registry["voices"]
    voice = voices.setdefault(stable_voice_id, {"active_version": None, "versions": {}})
    versions = voice["versions"]
    if version in versions:
        raise RegistryError("artifact_version_exists")
    entry = {
        "artifact_sha256": artifact_sha256,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "language": language,
        "state": "staged",
        "rollback_retained": True,
    }
    versions[version] = entry
    _save_registry(registry_path, registry)
    return entry


def detach_rollback_reference(
    *,
    registry_path: Path,
    stable_voice_id: str,
    version: str,
    expected_artifact_sha256: str,
) -> dict[str, object]:
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][stable_voice_id]
        entry = voice["versions"][version]
    except KeyError as error:
        raise RegistryError("registry_version_missing") from error
    if entry["artifact_sha256"] != expected_artifact_sha256:
        raise RegistryError("artifact_digest_mismatch")
    if voice.get("active_version") == version or entry["state"] == "active":
        raise RegistryError("active_reference_detach_forbidden")
    entry["rollback_retained"] = False
    _save_registry(registry_path, registry)
    return entry


def set_version_state(
    *,
    registry_path: Path,
    stable_voice_id: str,
    version: str,
    expected_artifact_sha256: str,
    state: str,
) -> dict[str, str]:
    if state not in VERSION_STATES:
        raise RegistryError("registry_state_invalid")
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][stable_voice_id]
        entry = voice["versions"][version]
    except KeyError as error:
        raise RegistryError("registry_version_missing") from error
    if entry["artifact_sha256"] != expected_artifact_sha256:
        raise RegistryError("artifact_digest_mismatch")
    if entry["state"] == "deleted" or (state == "staged" and entry["state"] != "staged"):
        raise RegistryError("registry_transition_invalid")
    if state == "active":
        prior = voice.get("active_version")
        if prior and prior != version:
            voice["versions"][prior]["state"] = "retired"
        voice["active_version"] = version
    elif voice.get("active_version") == version:
        voice["active_version"] = None
    entry["state"] = state
    _save_registry(registry_path, registry)
    return entry


def retire_version(
    *,
    registry_path: Path,
    stable_voice_id: str,
    version: str,
    expected_artifact_sha256: str,
) -> dict[str, str]:
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][stable_voice_id]
        entry = voice["versions"][version]
    except KeyError as error:
        raise RegistryError("registry_version_missing") from error
    if entry["artifact_sha256"] != expected_artifact_sha256:
        raise RegistryError("artifact_digest_mismatch")
    if voice.get("active_version") == version:
        raise RegistryError("active_version_retirement_forbidden")
    if entry["state"] == "deleted":
        raise RegistryError("registry_transition_invalid")
    entry["state"] = "retired"
    _save_registry(registry_path, registry)
    return entry


def rollback_version(
    *,
    registry_path: Path,
    stable_voice_id: str,
    version: str,
    expected_artifact_sha256: str,
    health_probe: Callable[[dict[str, str]], bool],
) -> dict[str, str]:
    registry = load_registry(registry_path)
    try:
        voice = registry["voices"][stable_voice_id]
        entry = voice["versions"][version]
    except KeyError as error:
        raise RegistryError("registry_version_missing") from error
    if entry["artifact_sha256"] != expected_artifact_sha256:
        raise RegistryError("artifact_digest_mismatch")
    if entry["state"] not in {"retired", "unhealthy"}:
        raise RegistryError("rollback_target_invalid")
    if not health_probe(entry):
        raise RegistryError("rollback_health_failed")
    prior = voice.get("active_version")
    if prior and prior != version:
        voice["versions"][prior]["state"] = "retired"
    entry["state"] = "active"
    voice["active_version"] = version
    _save_registry(registry_path, registry)
    return entry


def reconcile_registry(
    *,
    registry_path: Path,
    loaded_artifacts: dict[str, str],
) -> list[dict[str, str]]:
    """Fail active mappings closed when the provider's loaded digest drifts."""

    registry = load_registry(registry_path)
    findings: list[dict[str, str]] = []
    voices = registry["voices"]
    for voice_id, voice in voices.items():
        active_version = voice.get("active_version")
        if not active_version:
            continue
        entry = voice["versions"].get(active_version)
        loaded_digest = loaded_artifacts.get(voice_id)
        if not entry or loaded_digest is None:
            if entry:
                entry["state"] = "unhealthy"
            voice["active_version"] = None
            findings.append({"voice_id": voice_id, "reason": "active_artifact_missing"})
        elif loaded_digest != entry["artifact_sha256"]:
            entry["state"] = "unhealthy"
            voice["active_version"] = None
            findings.append({"voice_id": voice_id, "reason": "active_artifact_digest_mismatch"})
    for voice_id in sorted(set(loaded_artifacts) - set(voices)):
        if VOICE_ID_RE.fullmatch(voice_id):
            findings.append({"voice_id": voice_id, "reason": "unexpected_custom_artifact"})
    if findings:
        _save_registry(registry_path, registry)
    return findings


def discover_active(registry_path: Path) -> dict[str, dict[str, str]]:
    registry = load_registry(registry_path)
    discovered: dict[str, dict[str, str]] = {}
    for voice_id, voice in registry["voices"].items():
        active_version = voice.get("active_version")
        if not active_version:
            continue
        entry = voice["versions"].get(active_version)
        if entry and entry.get("state") == "active":
            discovered[voice_id] = {"version": active_version, **entry}
    return discovered


def registry_health(registry_path: Path) -> dict[str, object]:
    registry = load_registry(registry_path)
    counts = {state: 0 for state in sorted(VERSION_STATES)}
    for voice in registry["voices"].values():
        for entry in voice["versions"].values():
            state = entry.get("state")
            if state not in VERSION_STATES:
                raise RegistryError("registry_state_invalid")
            counts[state] += 1
    return {
        "schema_version": "custom-voice-registry-health.v1",
        "voice_count": len(registry["voices"]),
        "version_state_counts": counts,
        "active_discovery_count": len(discover_active(registry_path)),
    }
