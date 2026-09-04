"""Drained blue/green activation for the pinned Kokoro provider.

The orchestration callbacks are deliberately injected.  Production may bind them
to a narrowly scoped host-side service; the private API and build workers never
need a Docker socket or permission to mutate a running provider.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .registry import RegistryError, set_version_state

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VOICE_ID_RE = re.compile(r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERSION_RE = re.compile(r"^v[1-9][0-9]*$")
SLOTS = frozenset({"blue", "green"})


class BlueGreenError(RuntimeError):
    """Content-free activation failure safe to expose to an operator."""


def provider_voice_id(stable_voice_id: str) -> str:
    """Map a reserved stable ID to a Kokoro-safe non-blend filename."""

    if not VOICE_ID_RE.fullmatch(stable_voice_id):
        raise BlueGreenError("voice_id_invalid")
    return "cv_" + stable_voice_id.replace("-", "_")


@dataclass(frozen=True)
class ProviderOperations:
    active_slot: Callable[[], str]
    wait_drained: Callable[[str], bool]
    start: Callable[[str, Path], None]
    stop: Callable[[str], None]
    discover: Callable[[str], set[str]]
    synthesize: Callable[[str, str], bytes]
    switch_traffic: Callable[[str], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_artifact(path: Path, expected_sha256: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise BlueGreenError("artifact_unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise BlueGreenError("artifact_invalid")
    if not SHA256_RE.fullmatch(expected_sha256) or _sha256(path) != expected_sha256:
        raise BlueGreenError("artifact_digest_mismatch")


def _remove_snapshot(path: Path) -> None:
    if not path.exists():
        return
    os.chmod(path, 0o700)
    for child in path.iterdir():
        if child.is_file() and not child.is_symlink():
            os.chmod(child, 0o600)
    shutil.rmtree(path)


def publish_snapshot(
    *,
    snapshot_root: Path,
    slot: str,
    artifacts: Mapping[str, tuple[Path, str]],
) -> Path:
    """Atomically publish one immutable, read-only provider voice snapshot."""

    if slot not in SLOTS:
        raise BlueGreenError("provider_slot_invalid")
    for voice_id, (path, digest) in artifacts.items():
        if not VOICE_ID_RE.fullmatch(voice_id):
            raise BlueGreenError("voice_id_invalid")
        _validate_artifact(path, digest)

    snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = snapshot_root / slot
    temporary = Path(tempfile.mkdtemp(prefix=f".{slot}-", dir=snapshot_root))
    try:
        for voice_id, (source, digest) in sorted(artifacts.items()):
            destination = temporary / f"{provider_voice_id(voice_id)}.pt"
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o444)
            if _sha256(destination) != digest:
                raise BlueGreenError("artifact_copy_mismatch")
        previous = snapshot_root / f".{slot}-previous"
        _remove_snapshot(previous)
        if target.exists():
            os.chmod(target, 0o700)
            os.replace(target, previous)
        os.replace(temporary, target)
        os.chmod(target, 0o555)
        _remove_snapshot(previous)
        return target
    finally:
        if temporary.exists():
            os.chmod(temporary, 0o700)
            shutil.rmtree(temporary)


def activate_blue_green(
    *,
    registry_path: Path,
    snapshot_root: Path,
    stable_voice_id: str,
    version: str,
    artifact_path: Path,
    expected_sha256: str,
    active_artifacts: Mapping[str, tuple[Path, str]],
    operations: ProviderOperations,
) -> dict[str, str]:
    """Probe a fresh provider, switch traffic, then commit the registry."""

    if not VOICE_ID_RE.fullmatch(stable_voice_id):
        raise BlueGreenError("voice_id_invalid")
    if not VERSION_RE.fullmatch(version):
        raise BlueGreenError("voice_version_invalid")
    _validate_artifact(artifact_path, expected_sha256)
    current = operations.active_slot()
    if current not in SLOTS:
        raise BlueGreenError("provider_slot_invalid")
    candidate = "green" if current == "blue" else "blue"
    snapshot = publish_snapshot(
        snapshot_root=snapshot_root,
        slot=candidate,
        artifacts={**active_artifacts, stable_voice_id: (artifact_path, expected_sha256)},
    )
    provider_id = provider_voice_id(stable_voice_id)
    started = False
    switched = False
    try:
        operations.start(candidate, snapshot)
        started = True
        if provider_id not in operations.discover(candidate):
            raise BlueGreenError("activation_discovery_failed")
        audio = operations.synthesize(candidate, provider_id)
        if not isinstance(audio, bytes) or len(audio) < 4:
            raise BlueGreenError("activation_health_failed")
        if not operations.wait_drained(current):
            raise BlueGreenError("provider_drain_timeout")
        operations.switch_traffic(candidate)
        switched = True
        try:
            set_version_state(
                registry_path=registry_path,
                stable_voice_id=stable_voice_id,
                version=version,
                expected_artifact_sha256=expected_sha256,
                state="active",
            )
        except RegistryError as error:
            raise BlueGreenError("registry_switch_failed") from error
        operations.stop(current)
        return {"slot": candidate, "stable_voice_id": stable_voice_id, "version": version, "artifact_sha256": expected_sha256}
    except Exception:
        if switched:
            operations.switch_traffic(current)
        if started:
            operations.stop(candidate)
        raise
