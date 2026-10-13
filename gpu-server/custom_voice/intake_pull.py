"""Signed intake pull: fetch HeartCode's samples into an immutable local intake.

The build pipeline stays filesystem-only (`intake.prepare_workspace` reads a
digest-bound `benchmark-intake.v1` directory). This module is the one place that
turns a contract `IntakeRequest` into that directory: it fetches each sample
from an operator allow-listed origin, never follows redirects, caps bytes,
verifies every SHA-256 and the declared PCM format, and only then publishes the
directory atomically. Errors are content-free reason codes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import wave
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from .intake import IntakeProfile

ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VOICE_ID_RE = re.compile(r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERSION_RE = re.compile(r"^v[1-9][0-9]{0,8}$")
AUTHORIZATION_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
FINGERPRINT_FILE = ".intake-request.sha256"
# Fields that define an intake's content. fetch_url is excluded on purpose:
# HeartCode re-signs URLs (they expire), so a retry carries new URLs for the
# same content and must return the existing manifest without refetching.
SAMPLE_CONTENT_FIELDS = ("sample_id", "role", "audio_sha256", "transcript", "sample_rate_hz", "channels", "encoding")
REQUEST_CONTENT_FIELDS = ("schema_version", "intake_id", "stable_voice_id", "version", "language", "authorization_id", "builder_profile")


class IntakePullError(ValueError):
    """Safe intake-pull failure; the message is a reason code only."""


class IntakeConflict(IntakePullError):
    """The intake ID already exists with different content."""


# fetch(url, max_bytes) -> (status_code, body). Must not follow redirects and
# must stop reading past max_bytes (returning more than max_bytes is an error).
Fetch = Callable[[str, int], tuple[int, bytes]]


def httpx_fetch(timeout_seconds: float = 30.0) -> Fetch:
    import httpx

    def fetch(url: str, max_bytes: int) -> tuple[int, bytes]:
        with httpx.Client(follow_redirects=False, timeout=timeout_seconds) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return response.status_code, b""
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise IntakePullError("intake_sample_too_large")
                    chunks.append(chunk)
                return 200, b"".join(chunks)

    return fetch


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise IntakePullError("intake_fetch_url_invalid")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def normalize_origins(origins: Iterable[str]) -> frozenset[str]:
    return frozenset(_origin(origin.rstrip("/") + "/") for origin in origins if origin.strip())


def request_fingerprint(request: dict) -> str:
    content = {field: request.get(field) for field in REQUEST_CONTENT_FIELDS}
    content["samples"] = [
        {field: sample.get(field) for field in SAMPLE_CONTENT_FIELDS}
        for sample in sorted(request.get("samples") or [], key=lambda item: str(item.get("sample_id")))
    ]
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_request(request: dict, profile: IntakeProfile) -> None:
    if request.get("schema_version") != "custom-voice-intake-request.v1":
        raise IntakePullError("intake_schema_unsupported")
    if not ID_RE.fullmatch(str(request.get("intake_id", ""))):
        raise IntakePullError("intake_id_invalid")
    if not VOICE_ID_RE.fullmatch(str(request.get("stable_voice_id", ""))):
        raise IntakePullError("stable_voice_id_invalid")
    if not VERSION_RE.fullmatch(str(request.get("version", ""))):
        raise IntakePullError("artifact_version_invalid")
    if request.get("language") not in profile.allowed_languages:
        raise IntakePullError("language_unsupported")
    if not AUTHORIZATION_RE.fullmatch(str(request.get("authorization_id", ""))):
        raise IntakePullError("authorization_invalid")
    if request.get("builder_profile") != profile.name:
        raise IntakePullError("builder_profile_unsupported")
    samples = request.get("samples")
    if not isinstance(samples, list):
        raise IntakePullError("samples_invalid")
    roles = [sample.get("role") for sample in samples if isinstance(sample, dict)]
    if len(roles) != len(samples) or roles.count("adaptation") != profile.adaptation_count or roles.count("heldout") != profile.heldout_count:
        raise IntakePullError("sample_count_invalid")
    seen: set[str] = set()
    for sample in samples:
        sample_id = str(sample.get("sample_id", ""))
        if not ID_RE.fullmatch(sample_id):
            raise IntakePullError("sample_id_invalid")
        if sample_id in seen:
            raise IntakePullError("sample_id_duplicate")
        seen.add(sample_id)
        if not SHA256_RE.fullmatch(str(sample.get("audio_sha256", ""))):
            raise IntakePullError("audio_digest_invalid")
        transcript = sample.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip() or "\x00" in transcript:
            raise IntakePullError("transcript_invalid")
        if len(transcript.encode("utf-8")) > profile.max_transcript_bytes:
            raise IntakePullError("transcript_too_large")
        if sample.get("channels") != 1 or sample.get("encoding") != "pcm_s16le" or sample.get("sample_rate_hz") not in range(8_000, 192_001):
            raise IntakePullError("sample_metadata_invalid")
        _origin(str(sample.get("fetch_url", "")))


def _check_pcm(content: bytes, sample: dict) -> None:
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getcomptype() != "NONE":
                raise IntakePullError("intake_audio_format_mismatch")
            if source.getframerate() != sample["sample_rate_hz"]:
                raise IntakePullError("intake_audio_format_mismatch")
    except (wave.Error, EOFError) as error:
        raise IntakePullError("intake_audio_decode_failed") from error


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(content)
        destination.flush()
        os.fsync(destination.fileno())


def _existing(intake_dir: Path, fingerprint: str) -> dict[str, object] | None:
    try:
        stored = (intake_dir / FINGERPRINT_FILE).read_text(encoding="utf-8").strip()
        manifest = (intake_dir / "manifest.json").read_bytes()
    except FileNotFoundError:
        raise IntakeConflict("intake_conflict") from None
    if stored != fingerprint:
        raise IntakeConflict("intake_conflict")
    return {"manifest_sha256": hashlib.sha256(manifest).hexdigest(), "sample_count": len(json.loads(manifest)["samples"])}


def pull_intake(
    request: dict,
    *,
    intake_root: Path,
    allowed_origins: frozenset[str],
    fetch: Fetch,
    profile: IntakeProfile = IntakeProfile(),
) -> dict[str, object]:
    """Fetch, verify and atomically publish one intake; idempotent per intake_id."""

    validate_request(request, profile)
    intake_id = request["intake_id"]
    fingerprint = request_fingerprint(request)
    intake_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    intake_dir = intake_root / intake_id
    if intake_dir.exists() or intake_dir.is_symlink():
        if intake_dir.is_symlink() or not intake_dir.is_dir():
            raise IntakeConflict("intake_conflict")
        existing = _existing(intake_dir, fingerprint)
        return {"schema_version": "custom-voice-intake.v1", "intake_id": intake_id, **existing}
    if not allowed_origins:
        raise IntakePullError("intake_origins_unconfigured")
    for sample in request["samples"]:
        if _origin(sample["fetch_url"]) not in allowed_origins:
            raise IntakePullError("intake_origin_forbidden")

    temporary = Path(tempfile.mkdtemp(prefix=f".{intake_id}-", dir=intake_root))
    os.chmod(temporary, 0o700)
    try:
        (temporary / "samples").mkdir(mode=0o700)
        remaining = profile.max_total_bytes
        manifest_samples = []
        for sample in sorted(request["samples"], key=lambda item: item["sample_id"]):
            status, content = fetch(sample["fetch_url"], remaining)
            if 300 <= status < 400:
                raise IntakePullError("intake_fetch_redirect_refused")
            if status != 200:
                raise IntakePullError("intake_fetch_failed")
            if len(content) > remaining:
                raise IntakePullError("intake_sample_too_large")
            remaining -= len(content)
            if hashlib.sha256(content).hexdigest() != sample["audio_sha256"]:
                raise IntakePullError("audio_digest_mismatch")
            _check_pcm(content, sample)
            sample_id = sample["sample_id"]
            _write_private(temporary / "samples" / f"{sample_id}.wav", content)
            _write_private(temporary / "samples" / f"{sample_id}.txt", sample["transcript"].encode("utf-8"))
            manifest_samples.append({
                "sample_id": sample_id,
                "role": sample["role"],
                "audio_path": f"samples/{sample_id}.wav",
                "transcript_path": f"samples/{sample_id}.txt",
                "audio_sha256": sample["audio_sha256"],
                "sample_rate_hz": sample["sample_rate_hz"],
                "channels": 1,
                "encoding": "pcm_s16le",
            })
        manifest = {
            "schema_version": "benchmark-intake.v1",
            "intake_id": intake_id,
            "stable_voice_id": request["stable_voice_id"],
            "version": request["version"],
            "builder_profile": request["builder_profile"],
            "authorization_id": request["authorization_id"],
            "authorization_scope": "production",
            "language": request["language"],
            "samples": manifest_samples,
        }
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        _write_private(temporary / "manifest.json", encoded)
        _write_private(temporary / FINGERPRINT_FILE, fingerprint.encode())
        try:
            os.rename(temporary, intake_dir)
        except OSError:
            # Lost a race with an identical retry: the winner's content decides.
            existing = _existing(intake_dir, fingerprint)
            return {"schema_version": "custom-voice-intake.v1", "intake_id": intake_id, **existing}
        return {
            "schema_version": "custom-voice-intake.v1",
            "intake_id": intake_id,
            "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
            "sample_count": len(manifest_samples),
        }
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
