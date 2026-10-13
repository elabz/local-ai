"""Registry lifecycle behind the control plane: stage, activate, rollback, retire, delete.

Two files describe serving state and both must move together:
- the registry (`registry.py`, `custom-voice-registry.v1`), the record of every
  version and which one is active;
- the speech gateway's map (`custom-voice-map.json`), which is what
  `/v1/audio/speech` actually resolves a `custom-*` voice through.

Activation and rollback keep exactly the evidence checks the gateway's own
`/internal/v1/voice-registry/{id}/activate` performs: registry entry, sealed
artifact bytes, SBOM bytes, the digest-bound HeartCode attestation, the
unresolved-licence count recomputed from the SBOM, and Kokoro discovery of the
provider voice. A failed check leaves both files untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .blue_green import provider_voice_id
from .garbage_collection import DeletionError, execute_deletion, request_deletion
from .registry import (
    RegistryError,
    detach_rollback_reference,
    load_registry,
    retire_version,
    rollback_version,
    set_version_state,
    stage_version,
)

UNRESOLVED_LICENSES = {None, "", "NOASSERTION", "NONE"}
PREVIEW_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Written by the runner beside the sealed artifact: the review preview IDs, so
# deletion can find them (previews live flat under the preview root).
PREVIEWS_FILE = "previews.json"


class LifecycleError(ValueError):
    """Safe lifecycle failure; the message is a lower_snake reason code."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".custom-voice-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class Lifecycle:
    registry_path: Path
    map_path: Path
    artifact_root: Path
    deletion_queue: Path
    preview_root: Path
    # discover() -> the provider voice IDs Kokoro currently serves.
    discover: Callable[[], set[str]]

    # -- helpers -----------------------------------------------------------

    def _version_root(self, voice_id: str, version: str) -> Path:
        return self.artifact_root / voice_id / version

    def _artifact_manifest(self, voice_id: str, version: str, artifact_sha256: str) -> tuple[dict, str]:
        path = self._version_root(voice_id, version) / "manifest.json"
        try:
            raw = path.read_bytes()
            manifest = json.loads(raw)
        except (OSError, ValueError) as error:
            raise LifecycleError("artifact_missing") from error
        if manifest.get("artifact", {}).get("sha256") != artifact_sha256 or manifest.get("stable_voice_id") != voice_id or manifest.get("version") != version:
            raise LifecycleError("artifact_digest_mismatch")
        return manifest, hashlib.sha256(raw).hexdigest()

    def _verify_activation_evidence(self, payload: dict) -> dict:
        voice_id, version = payload["stable_voice_id"], payload["version"]
        artifact_sha256, sbom_sha256 = payload["artifact_sha256"], payload["sbom_sha256"]
        attestation = payload.get("admin_attestation") or {}
        try:
            entry = load_registry(self.registry_path)["voices"][voice_id]["versions"][version]
        except (KeyError, RegistryError) as error:
            raise LifecycleError("registry_version_missing") from error
        root = self._version_root(voice_id, version)
        artifact_path = root / f"{artifact_sha256}.pt"
        sbom_path = root / "sbom.spdx.json"
        try:
            artifact_ok = _sha256_file(artifact_path) == artifact_sha256
            sbom_ok = _sha256_file(sbom_path) == sbom_sha256
            packages = json.loads(sbom_path.read_text(encoding="utf-8")).get("packages", [])
        except (OSError, ValueError) as error:
            raise LifecycleError("activation_evidence_rejected") from error
        unresolved = sum(1 for package in packages if package.get("licenseConcluded") in UNRESOLVED_LICENSES)
        evidence_ok = (
            entry.get("artifact_sha256") == artifact_sha256
            and artifact_ok
            and sbom_ok
            and payload.get("admin_attestation_id") == attestation.get("attestation_id")
            and attestation.get("status") == "approved"
            and attestation.get("scope") == "internal_pea"
            and attestation.get("artifact_sha256") == artifact_sha256
            and attestation.get("sbom_sha256") == sbom_sha256
            and attestation.get("speaker_authority_confirmed") is True
            and attestation.get("no_redistribution_confirmed") is True
            and attestation.get("license_findings_acknowledged") is True
            and attestation.get("unresolved_license_count") == unresolved
        )
        if not evidence_ok:
            raise LifecycleError("activation_evidence_rejected")
        if provider_voice_id(voice_id) not in self.discover():
            # The provider has not loaded this voice's bytes (blue/green load is
            # an operator step); never map a voice Kokoro cannot synthesize.
            raise LifecycleError("activation_discovery_failed")
        return entry

    def _map_voice(self, voice_id: str, language: str) -> None:
        try:
            mapping = json.loads(self.map_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mapping = {"voices": {}}
        mapping.setdefault("voices", {})[voice_id] = {"provider_voice_id": provider_voice_id(voice_id), "language": language}
        _atomic_json(self.map_path, mapping)

    def _unmap_voice(self, voice_id: str) -> None:
        try:
            mapping = json.loads(self.map_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if mapping.get("voices", {}).pop(voice_id, None) is not None:
            _atomic_json(self.map_path, mapping)

    @staticmethod
    def _version_view(voice_id: str, version: str, entry: dict) -> dict:
        return {"stable_voice_id": voice_id, "version": version, "artifact_sha256": entry["artifact_sha256"], "state": entry["state"]}

    # -- contract operations ---------------------------------------------------

    def stage(self, payload: dict) -> dict:
        """Stage a sealed version; the manifest digest and language come from its own seal."""

        voice_id, version, digest = payload["stable_voice_id"], payload["version"], payload["artifact_sha256"]
        manifest, manifest_sha256 = self._artifact_manifest(voice_id, version, digest)
        existing = load_registry(self.registry_path)["voices"].get(voice_id, {}).get("versions", {}).get(version)
        if existing is not None:
            # The runner already stages a successful build for review; staging
            # again is an idempotent read of that entry.
            if existing["artifact_sha256"] != digest:
                raise LifecycleError("artifact_version_exists")
            return self._version_view(voice_id, version, existing)
        try:
            entry = stage_version(
                registry_path=self.registry_path,
                stable_voice_id=voice_id,
                version=version,
                artifact_sha256=digest,
                artifact_manifest_sha256=manifest_sha256,
                language=str(manifest.get("language", "")),
            )
        except RegistryError as error:
            raise LifecycleError(str(error)) from error
        return self._version_view(voice_id, version, entry)

    def activate(self, payload: dict) -> dict:
        voice_id, version = payload["stable_voice_id"], payload["version"]
        entry = self._verify_activation_evidence(payload)
        if entry.get("state") not in {"staged", "active", "retired", "unhealthy"}:
            raise LifecycleError("registry_transition_invalid")
        self._map_voice(voice_id, entry.get("language", "a"))
        try:
            entry = set_version_state(
                registry_path=self.registry_path,
                stable_voice_id=voice_id,
                version=version,
                expected_artifact_sha256=payload["artifact_sha256"],
                state="active",
            )
        except RegistryError as error:
            raise LifecycleError(str(error)) from error
        return self._version_view(voice_id, version, entry)

    def rollback(self, payload: dict) -> dict:
        voice_id, version = payload["stable_voice_id"], payload["version"]
        entry = self._verify_activation_evidence(payload)
        try:
            entry = rollback_version(
                registry_path=self.registry_path,
                stable_voice_id=voice_id,
                version=version,
                expected_artifact_sha256=payload["artifact_sha256"],
                health_probe=lambda _entry: True,  # discovery was probed with the evidence
            )
        except RegistryError as error:
            raise LifecycleError(str(error)) from error
        self._map_voice(voice_id, entry.get("language", "a"))
        return self._version_view(voice_id, version, entry)

    def retire(self, payload: dict) -> dict:
        """Retire an exact version. Retiring the active one takes the voice out of service."""

        voice_id, version, digest = payload["stable_voice_id"], payload["version"], payload["artifact_sha256"]
        try:
            voice = load_registry(self.registry_path)["voices"][voice_id]
            is_active = voice.get("active_version") == version
            if is_active:
                # Unmap first: a voice must never be served from a retired version.
                self._unmap_voice(voice_id)
                entry = set_version_state(registry_path=self.registry_path, stable_voice_id=voice_id, version=version, expected_artifact_sha256=digest, state="retired")
            else:
                entry = retire_version(registry_path=self.registry_path, stable_voice_id=voice_id, version=version, expected_artifact_sha256=digest)
        except KeyError as error:
            raise LifecycleError("registry_version_missing") from error
        except RegistryError as error:
            raise LifecycleError(str(error)) from error
        return self._version_view(voice_id, version, entry)

    def delete(self, payload: dict) -> dict:
        """Run reference-aware deletion of an inactive version and its previews."""

        voice_id, version, digest = payload["stable_voice_id"], payload["version"], payload["artifact_sha256"]
        version_root = self._version_root(voice_id, version)
        try:
            preview_ids = [
                str(item) for item in json.loads((version_root / PREVIEWS_FILE).read_text(encoding="utf-8"))
                if PREVIEW_ID_RE.fullmatch(str(item))
            ]
        except (OSError, ValueError):
            preview_ids = []
        try:
            detach_rollback_reference(registry_path=self.registry_path, stable_voice_id=voice_id, version=version, expected_artifact_sha256=digest)
            request = request_deletion(
                registry_path=self.registry_path,
                queue_root=self.deletion_queue,
                stable_voice_id=voice_id,
                version=version,
                expected_artifact_sha256=digest,
                targets={"artifact": version_root},
            )
        except RegistryError as error:
            raise LifecycleError(str(error)) from error
        except DeletionError as error:
            if str(error) == "deletion_already_requested":
                return self.deletion(_request_id(voice_id, version, digest))
            raise LifecycleError(str(error)) from error
        request_id = str(request["request_id"])
        try:
            execute_deletion(registry_path=self.registry_path, queue_root=self.deletion_queue, request_id=request_id, allowed_roots={"artifact": self.artifact_root})
            for preview_id in preview_ids:
                (self.preview_root / f"{preview_id}.wav").unlink(missing_ok=True)
        except (DeletionError, OSError):
            return {"request_id": request_id, "state": "failed"}
        return self.deletion(request_id)

    def deletion(self, request_id: str) -> dict:
        path = self.deletion_queue / f"{request_id}.json"
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise LifecycleError("deletion_missing") from error
        state = request.get("state")
        return {"request_id": request_id, "state": state if state in {"queued", "verified_deleted", "failed"} else "failed"}

    def registry_view(self) -> dict:
        registry = load_registry(self.registry_path)
        voices = []
        for voice_id, voice in sorted(registry["voices"].items()):
            voices.append({
                "stable_voice_id": voice_id,
                "active_version": voice.get("active_version"),
                "versions": [self._version_view(voice_id, version, entry) for version, entry in sorted(voice.get("versions", {}).items())],
            })
        return {"schema_version": "custom-voice-registry-view.v1", "voices": voices}


def _request_id(voice_id: str, version: str, digest: str) -> str:
    return hashlib.sha256(f"{voice_id}:{version}:{digest}".encode()).hexdigest()[:32]
