"""Exact-digest, health-probed atomic custom-voice registry switching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VOICE_ID_RE = re.compile(r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERSION_RE = re.compile(r"^v[1-9][0-9]*$")


class ActivationError(RuntimeError):
    """Safe activation failure containing no host path or content."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def activate_exact_digest(
    *,
    registry_path: str | Path,
    artifact_path: str | Path,
    voice_id: str,
    version: str,
    expected_sha256: str,
    health_probe: Callable[[Path], bool],
) -> dict[str, str]:
    """Probe first and atomically replace the mapping only after success."""

    registry = Path(registry_path)
    artifact = Path(artifact_path)
    if not VOICE_ID_RE.fullmatch(voice_id):
        raise ActivationError("voice_id_invalid")
    if not VERSION_RE.fullmatch(version):
        raise ActivationError("voice_version_invalid")
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ActivationError("artifact_digest_invalid")
    if not artifact.is_file() or _sha256(artifact) != expected_sha256:
        raise ActivationError("artifact_digest_mismatch")
    if not health_probe(artifact):
        raise ActivationError("activation_health_failed")

    current: dict[str, dict[str, str]] = {}
    if registry.exists():
        current = json.loads(registry.read_text(encoding="utf-8"))
    updated = dict(current)
    updated[voice_id] = {
        "version": version,
        "artifact_sha256": expected_sha256,
        "state": "active",
    }

    registry.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".registry-", dir=registry.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(updated, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, registry)
        directory_fd = os.open(registry.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return updated[voice_id]
