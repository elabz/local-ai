"""Root-confined intake validation and deterministic workspace preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .audio_quality import analyze_pcm16_wav

ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class IntakeProfile:
    name: str = "kvoicewalk-multireference.v1"
    adaptation_count: int = 6
    heldout_count: int = 4
    min_duration_seconds: float = 5.0
    max_duration_seconds: float = 35.0
    max_total_bytes: int = 200 * 1024 * 1024
    max_transcript_bytes: int = 16 * 1024
    allowed_languages: tuple[str, ...] = ("en-US",)
    output_rate_hz: int = 24_000
    silence_amplitude: int = 104  # approximately -50 dBFS for PCM16
    max_silence_fraction: float = 0.80
    min_rms_dbfs: float = -45.0
    min_words_per_minute: float = 40.0
    max_words_per_minute: float = 260.0


@dataclass(frozen=True)
class SampleFinding:
    sample_id: str
    role: str
    duration_seconds: float
    source_rate_hz: int
    rms_dbfs: float
    silence_fraction: float
    words_per_minute: float
    clipping_outcome: str
    reason_codes: tuple[str, ...]


class IntakeError(RuntimeError):
    """Safe intake failure containing no host path or transcript content."""


def _validate_id(value: object, code: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise IntakeError(code)
    return value


def _relative_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise IntakeError("manifest_path_invalid")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise IntakeError("manifest_path_invalid")
    return candidate.parts


def _secure_open(root_fd: int, parts: tuple[str, ...]) -> int:
    directory_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise IntakeError("input_open_rejected") from error
    finally:
        os.close(directory_fd)


def _check_regular(metadata: os.stat_result, expected_uid: int | None) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise IntakeError("input_not_regular")
    if metadata.st_nlink != 1:
        raise IntakeError("input_hardlink_rejected")
    if expected_uid is not None and metadata.st_uid != expected_uid:
        raise IntakeError("input_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise IntakeError("input_mode_invalid")


def _check_directory(metadata: os.stat_result, expected_uid: int | None) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise IntakeError("intake_directory_invalid")
    if expected_uid is not None and metadata.st_uid != expected_uid:
        raise IntakeError("input_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise IntakeError("input_mode_invalid")


def _copy_fd(source_fd: int, destination: Path, expected_uid: int | None, quota_remaining: int) -> tuple[str, int]:
    before = os.fstat(source_fd)
    _check_regular(before, expected_uid)
    if before.st_size > quota_remaining:
        raise IntakeError("intake_quota_exceeded")
    digest = hashlib.sha256()
    copied = 0
    with os.fdopen(os.dup(source_fd), "rb", closefd=True) as source, destination.open("xb") as target:
        os.chmod(destination, 0o600)
        for block in iter(lambda: source.read(1024 * 1024), b""):
            copied += len(block)
            if copied > quota_remaining:
                raise IntakeError("intake_quota_exceeded")
            digest.update(block)
            target.write(block)
        target.flush()
        os.fsync(target.fileno())
    after = os.fstat(source_fd)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if identity(before) != identity(after) or copied != before.st_size:
        raise IntakeError("input_changed_during_copy")
    return digest.hexdigest(), copied


def _pcm_metrics(path: Path, profile: IntakeProfile) -> tuple[float, int, float, float]:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE" or source.getsampwidth() != 2 or source.getnchannels() != 1:
                raise IntakeError("audio_format_unsupported")
            rate = source.getframerate()
            frames = source.getnframes()
            samples = array("h", source.readframes(frames))
    except (wave.Error, EOFError) as error:
        raise IntakeError("audio_decode_failed") from error
    if not samples or rate < 8_000 or rate > 192_000:
        raise IntakeError("audio_format_unsupported")
    duration = frames / rate
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    rms_dbfs = 20 * math.log10(rms / 32768) if rms else float("-inf")
    silence_fraction = sum(abs(sample) <= profile.silence_amplitude for sample in samples) / len(samples)
    return duration, rate, rms_dbfs, silence_fraction


def _normalize(source: Path, destination: Path, rate: int) -> None:
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map_metadata", "-1", "-ac", "1", "-ar", str(rate),
        "-c:a", "pcm_s16le", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as error:
        raise IntakeError("audio_normalization_failed") from error
    os.chmod(destination, 0o600)


def prepare_workspace(
    *,
    intake_root: str | Path,
    intake_id: str,
    expected_manifest_sha256: str,
    workspace_root: str | Path,
    job_id: str,
    seed: int,
    expected_uid: int | None = None,
    profile: IntakeProfile = IntakeProfile(),
    step_limit: int = 10_000,
    population_limit: int = 10,
    checkpoint_interval: int = 100,
    runtime_free_vram_mib: int = 1_024,
    active_work_budget_seconds: int = 21_600,
    maximum_wall_lifetime_seconds: int = 86_400,
    plateau_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate one immutable intake and atomically publish its private workspace."""

    _validate_id(intake_id, "intake_id_invalid")
    _validate_id(job_id, "job_id_invalid")
    if not SHA256_RE.fullmatch(expected_manifest_sha256):
        raise IntakeError("manifest_digest_invalid")
    if not 1 <= step_limit <= 1_000_000:
        raise IntakeError("step_limit_invalid")
    if not 1 <= population_limit <= 100:
        raise IntakeError("population_limit_invalid")
    if not 1 <= checkpoint_interval <= step_limit:
        raise IntakeError("checkpoint_interval_invalid")
    if not 512 <= runtime_free_vram_mib <= 65_536:
        raise IntakeError("runtime_vram_reserve_invalid")
    if not 60 <= active_work_budget_seconds <= 604_800:
        raise IntakeError("active_work_budget_invalid")
    if not active_work_budget_seconds <= maximum_wall_lifetime_seconds <= 2_592_000:
        raise IntakeError("maximum_wall_lifetime_invalid")
    from .build_runtime import validate_plateau_policy
    try:
        plateau_policy = validate_plateau_policy(plateau_policy, step_limit)
    except ValueError as error:
        raise IntakeError("plateau_policy_invalid") from error
    workspace_root = Path(workspace_root)
    workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(workspace_root, 0o700)
    final_workspace = workspace_root / job_id
    if final_workspace.exists():
        raise IntakeError("workspace_exists")
    temporary = Path(tempfile.mkdtemp(prefix=f".{job_id}-", dir=workspace_root))
    os.chmod(temporary, 0o700)

    root_fd = intake_fd = -1
    try:
        root_fd = os.open(intake_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        _check_directory(os.fstat(root_fd), expected_uid)
        intake_fd = os.open(intake_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        _check_directory(os.fstat(intake_fd), expected_uid)
        manifest_fd = _secure_open(intake_fd, ("manifest.json",))
        try:
            manifest_copy = temporary / "manifest.json"
            manifest_digest, total_bytes = _copy_fd(manifest_fd, manifest_copy, expected_uid, profile.max_total_bytes)
        finally:
            os.close(manifest_fd)
        if manifest_digest != expected_manifest_sha256:
            raise IntakeError("manifest_digest_mismatch")
        try:
            manifest = json.loads(manifest_copy.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntakeError("manifest_invalid") from error
        if manifest.get("schema_version") != "benchmark-intake.v1":
            raise IntakeError("manifest_schema_unsupported")
        if manifest.get("authorization_scope") != "production" or not manifest.get("authorization_id"):
            raise IntakeError("authorization_invalid")
        if manifest.get("language") not in profile.allowed_languages:
            raise IntakeError("language_unsupported")

        samples = manifest.get("samples")
        if not isinstance(samples, list):
            raise IntakeError("samples_invalid")
        roles = [sample.get("role") for sample in samples if isinstance(sample, dict)]
        if roles.count("adaptation") != profile.adaptation_count or roles.count("heldout") != profile.heldout_count:
            raise IntakeError("sample_count_invalid")
        sample_ids: set[str] = set()
        raw_directory = temporary / "raw"
        sample_directory = temporary / "samples"
        raw_directory.mkdir(mode=0o700)
        sample_directory.mkdir(mode=0o700)
        findings: list[SampleFinding] = []
        plan_samples: list[dict[str, str]] = []

        for sample in samples:
            if not isinstance(sample, dict):
                raise IntakeError("sample_invalid")
            sample_id = _validate_id(sample.get("sample_id"), "sample_id_invalid")
            if sample_id in sample_ids:
                raise IntakeError("sample_id_duplicate")
            sample_ids.add(sample_id)
            role = sample.get("role")
            if role not in {"adaptation", "heldout"}:
                raise IntakeError("sample_role_invalid")
            if sample.get("sample_rate_hz") not in range(8_000, 192_001) or sample.get("channels") != 1 or sample.get("encoding") != "pcm_s16le":
                raise IntakeError("sample_metadata_invalid")
            audio_fd = _secure_open(intake_fd, _relative_parts(sample.get("audio_path")))
            transcript_fd = _secure_open(intake_fd, _relative_parts(sample.get("transcript_path")))
            raw_audio = raw_directory / f"{sample_id}.wav"
            raw_transcript = raw_directory / f"{sample_id}.txt"
            try:
                audio_digest, audio_bytes = _copy_fd(audio_fd, raw_audio, expected_uid, profile.max_total_bytes - total_bytes)
                total_bytes += audio_bytes
                transcript_digest, transcript_bytes = _copy_fd(transcript_fd, raw_transcript, expected_uid, profile.max_total_bytes - total_bytes)
                total_bytes += transcript_bytes
            finally:
                os.close(audio_fd)
                os.close(transcript_fd)
            if audio_digest != sample.get("audio_sha256"):
                raise IntakeError("audio_digest_mismatch")
            if transcript_bytes > profile.max_transcript_bytes:
                raise IntakeError("transcript_too_large")
            try:
                transcript = raw_transcript.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise IntakeError("transcript_encoding_invalid") from error
            if not transcript.strip() or "\x00" in transcript:
                raise IntakeError("transcript_invalid")

            duration, source_rate, rms_dbfs, silence_fraction = _pcm_metrics(raw_audio, profile)
            if not profile.min_duration_seconds <= duration <= profile.max_duration_seconds:
                raise IntakeError("audio_duration_invalid")
            word_count = len(transcript.split())
            words_per_minute = word_count * 60 / duration
            reasons: list[str] = []
            if rms_dbfs < profile.min_rms_dbfs:
                reasons.append("audio_too_quiet")
            if silence_fraction > profile.max_silence_fraction:
                reasons.append("audio_excessive_silence")
            if not profile.min_words_per_minute <= words_per_minute <= profile.max_words_per_minute:
                reasons.append("transcript_rate_out_of_range")
            clipping = analyze_pcm16_wav(raw_audio, sample_id=sample_id)
            if clipping.outcome == "reject":
                reasons.extend(clipping.reason_codes)
            if reasons:
                raise IntakeError(reasons[0])

            normalized_audio = sample_directory / f"{sample_id}.wav"
            normalized_transcript = sample_directory / f"{sample_id}.txt"
            _normalize(raw_audio, normalized_audio, profile.output_rate_hz)
            shutil.copyfile(raw_transcript, normalized_transcript)
            os.chmod(normalized_transcript, 0o600)
            finding_reasons = clipping.reason_codes if clipping.outcome == "review" else ()
            findings.append(SampleFinding(
                sample_id=sample_id,
                role=role,
                duration_seconds=duration,
                source_rate_hz=source_rate,
                rms_dbfs=rms_dbfs,
                silence_fraction=silence_fraction,
                words_per_minute=words_per_minute,
                clipping_outcome=clipping.outcome,
                reason_codes=finding_reasons,
            ))
            plan_samples.append({
                "sample_id": sample_id,
                "role": role,
                "audio_path": f"samples/{sample_id}.wav",
                "transcript_path": f"samples/{sample_id}.txt",
                "normalized_audio_sha256": hashlib.sha256(normalized_audio.read_bytes()).hexdigest(),
                "transcript_sha256": transcript_digest,
            })

        plan: dict[str, object] = {
            "builder_profile": profile.name,
            "manifest_sha256": manifest_digest,
            "seed": seed,
            "device": "cuda",
            "min_free_vram_mib": 5_000,
            "runtime_free_vram_mib": runtime_free_vram_mib,
            # Kept for old worker readers. Versioned workers use the two budgets below.
            "max_duration_seconds": active_work_budget_seconds,
            "active_work_budget_seconds": active_work_budget_seconds,
            "maximum_wall_lifetime_seconds": maximum_wall_lifetime_seconds,
            "require_live_health": True,
            "require_live_activity": True,
            "step_limit": step_limit,
            "population_limit": population_limit,
            "checkpoint_interval": checkpoint_interval,
            "scoring_backend": "early_rejection_sequential",
            "batch_backend_enabled": False,
            "plateau_policy": plateau_policy,
            "samples": plan_samples,
            "findings": [asdict(finding) for finding in findings],
        }
        plan_path = temporary / "build-plan.json"
        plan_path.write_text(json.dumps(plan, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.chmod(plan_path, 0o600)
        shutil.rmtree(raw_directory)
        os.replace(temporary, final_workspace)
        return {"workspace_id": job_id, "manifest_sha256": manifest_digest, "sample_count": len(plan_samples)}
    except (OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, IntakeError):
            raise
        raise IntakeError("intake_validation_failed") from error
    finally:
        if intake_fd >= 0:
            os.close(intake_fd)
        if root_fd >= 0:
            os.close(root_fd)
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake-root", type=Path, required=True)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-uid", type=int)
    parser.add_argument("--step-limit", type=int, default=10_000)
    arguments = parser.parse_args()
    try:
        result = prepare_workspace(
            intake_root=arguments.intake_root,
            intake_id=arguments.intake_id,
            expected_manifest_sha256=arguments.manifest_sha256,
            workspace_root=arguments.workspace_root,
            job_id=arguments.job_id,
            seed=arguments.seed,
            expected_uid=arguments.expected_uid,
            step_limit=arguments.step_limit,
        )
        print(json.dumps({"outcome": "succeeded", **result}, sort_keys=True, separators=(",", ":")))
    except IntakeError as error:
        print(json.dumps({"outcome": "failed", "reason": str(error)}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
