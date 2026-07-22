"""Deterministic, content-free runtime primitives for custom voice builds."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

CHECKPOINT_SCHEMA = "custom-voice-checkpoint.v2"
SCORING_BACKENDS = {"exhaustive_sequential", "early_rejection_sequential"}
SAFE_PHASES = {"preprocessing", "synthesis", "speaker_encoding", "hybrid_scoring", "live_wait", "checkpoint_write"}
SAFE_REASONS = {
    "none", "prepared_inputs_unsupported", "batch_unsupported", "batch_conformance_failed",
    "batch_performance_failed", "batch_vram_reserve_failed", "equivalence_failed",
}
FORBIDDEN_TELEMETRY_FRAGMENTS = {
    "text", "transcript", "audio", "credential", "secret", "token", "authorization",
    "path", "preview", "hash", "sha", "digest",
}


class CheckpointError(ValueError):
    """Content-free checkpoint validation failure."""


@dataclass
class PerformanceEvidence:
    backend: str = "exhaustive_sequential"
    backend_reason: str = "none"
    phase_seconds: dict[str, float] = field(default_factory=lambda: {name: 0.0 for name in sorted(SAFE_PHASES)})
    candidates: int = 0
    utterances: int = 0
    rejection_positions: dict[str, int] = field(default_factory=dict)
    backend_fallbacks: int = 0
    resumes: int = 0
    executed_steps: int = 0
    checkpoints: int = 0

    def __post_init__(self) -> None:
        if self.backend not in SCORING_BACKENDS or self.backend_reason not in SAFE_REASONS:
            raise ValueError("performance_backend_invalid")

    def add_duration(self, phase: str, seconds: float) -> None:
        if phase not in SAFE_PHASES or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("performance_duration_invalid")
        self.phase_seconds[phase] = min(31_536_000.0, self.phase_seconds.get(phase, 0.0) + seconds)

    def reject(self, position: int) -> None:
        if not 1 <= position <= 64:
            raise ValueError("performance_rejection_position_invalid")
        key = str(position)
        self.rejection_positions[key] = self.rejection_positions.get(key, 0) + 1

    def result(self) -> dict[str, Any]:
        value = {
            "backend": self.backend,
            "backend_reason": self.backend_reason,
            "phase_seconds": {key: round(value, 6) for key, value in self.phase_seconds.items()},
            "candidates": self.candidates,
            "utterances": self.utterances,
            "rejection_positions": dict(sorted(self.rejection_positions.items())),
            "backend_fallbacks": self.backend_fallbacks,
            "resumes": self.resumes,
            "executed_steps": self.executed_steps,
            "checkpoints": self.checkpoints,
        }
        validate_safe_telemetry(value)
        return value


class PreparedInputCache:
    """Build-local immutable cache; never exposes keys or values as evidence."""

    def __init__(self, prepare: Callable[[str], Any] | None):
        self._prepare = prepare
        self._values: dict[tuple[str, str], Any] = {}

    @property
    def supported(self) -> bool:
        return self._prepare is not None

    def get(self, text: str, identity: str) -> Any:
        if self._prepare is None:
            raise ValueError("prepared_inputs_unsupported")
        key = (identity, text)
        if key not in self._values:
            self._values[key] = self._prepare(text)
        return self._values[key]

    def clear(self) -> None:
        self._values.clear()


def select_batch_backend(
    sequential_probe: Callable[[], dict[str, Any]],
    batch_probe: Callable[[], dict[str, Any]] | None,
    *,
    minimum_speedup: float,
    reserve_mib: int,
) -> tuple[str, str]:
    """Gate within-candidate batching on deterministic correctness and resources."""
    if batch_probe is None:
        return "early_rejection_sequential", "batch_unsupported"
    try:
        sequential = sequential_probe()
        first = batch_probe()
        second = batch_probe()
    except Exception:
        return "early_rejection_sequential", "batch_conformance_failed"
    required = {"waveform_valid", "decisions", "ordering", "duration_seconds", "peak_gpu_used_mib"}
    if not required.issubset(sequential) or not required.issubset(first) or first != second:
        return "early_rejection_sequential", "batch_conformance_failed"
    if not first["waveform_valid"] or first["decisions"] != sequential["decisions"] or first["ordering"] != sequential["ordering"]:
        return "early_rejection_sequential", "batch_conformance_failed"
    if first["peak_gpu_used_mib"] > reserve_mib:
        return "early_rejection_sequential", "batch_vram_reserve_failed"
    if first["duration_seconds"] <= 0 or sequential["duration_seconds"] / first["duration_seconds"] < minimum_speedup:
        return "early_rejection_sequential", "batch_performance_failed"
    return "batch_within_candidate", "none"


def validate_safe_telemetry(value: Any) -> None:
    """Reject protected field names and unbounded/string payloads recursively."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_TELEMETRY_FRAGMENTS):
                raise ValueError("telemetry_protected_field")
            validate_safe_telemetry(child)
    elif isinstance(value, list):
        if len(value) > 128:
            raise ValueError("telemetry_value_invalid")
        for child in value:
            validate_safe_telemetry(child)
    elif isinstance(value, str):
        if value not in SCORING_BACKENDS | SAFE_REASONS and not value.isdigit():
            raise ValueError("telemetry_string_invalid")
    elif not isinstance(value, (int, float, bool, type(None))):
        raise ValueError("telemetry_value_invalid")


def score_candidate(
    voice: Any,
    texts: Iterable[Any],
    minimum: float,
    synthesize: Callable[[Any, Any], Any],
    target_similarity: Callable[[Any], float],
    hybrid_similarity: Callable[[Any, Any, float], dict[str, Any]],
    *,
    early_rejection: bool,
    evidence: PerformanceEvidence | None = None,
) -> dict[str, Any]:
    """Score in deterministic order; short-circuit only a proven zero score."""
    audios: list[Any] = []
    similarities: list[float] = []
    if evidence:
        evidence.candidates += 1
    for position, text in enumerate(texts, 1):
        audio = synthesize(text, voice)
        if evidence:
            evidence.utterances += 1
        similarity = float(target_similarity(audio))
        if not math.isfinite(similarity):
            raise ValueError("candidate_similarity_invalid")
        audios.append(audio)
        similarities.append(similarity)
        if early_rejection and similarity <= minimum:
            if evidence:
                evidence.reject(position)
            return {"audio": audios[0], "target_similarity": min(similarities), "score": 0.0, "rejected_at": position}
    similarity = min(similarities)
    result = {"audio": audios[0], "target_similarity": similarity, "score": 0.0, "rejected_at": None}
    if similarity > minimum:
        result.update(hybrid_similarity(audios[0], audios[1], similarity))
    return result


def validate_plateau_policy(policy: Any, step_limit: int) -> dict[str, Any] | None:
    if policy is None:
        return None
    if not isinstance(policy, dict) or set(policy) != {"name", "minimum_step", "consecutive_no_improvement"}:
        raise ValueError("plateau_policy_invalid")
    if policy["name"] != "plateau.v1":
        raise ValueError("plateau_policy_invalid")
    minimum = policy["minimum_step"]
    window = policy["consecutive_no_improvement"]
    if not isinstance(minimum, int) or not isinstance(window, int) or not 1 <= minimum <= step_limit or not 1 <= window <= step_limit:
        raise ValueError("plateau_policy_invalid")
    return dict(policy)


def should_stop_for_plateau(policy: dict[str, Any] | None, executed_steps: int, last_improvement_step: int) -> bool:
    return bool(policy and executed_steps >= policy["minimum_step"] and executed_steps - last_improvement_step >= policy["consecutive_no_improvement"])


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode_bytes(value: Any, *, maximum: int = 32 * 1024 * 1024) -> bytes:
    if not isinstance(value, str) or len(value) > maximum * 2:
        raise CheckpointError("checkpoint_unsafe_state")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise CheckpointError("checkpoint_unsafe_state") from error
    if len(decoded) > maximum:
        raise CheckpointError("checkpoint_unsafe_state")
    return decoded


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    envelope = {"schema_version": CHECKPOINT_SCHEMA, "payload": payload}
    envelope["integrity_sha256"] = hashlib.sha256(_canonical(envelope)).hexdigest()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(_canonical(envelope))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_checkpoint(path: Path, expected_identity: dict[str, Any], step_limit: int) -> dict[str, Any]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckpointError("checkpoint_corrupt") from error
    if envelope.get("schema_version") != CHECKPOINT_SCHEMA:
        raise CheckpointError("checkpoint_legacy_non_resumable")
    digest = envelope.pop("integrity_sha256", None)
    if not isinstance(digest, str) or not hmac.compare_digest(digest, hashlib.sha256(_canonical(envelope)).hexdigest()):
        raise CheckpointError("checkpoint_integrity_invalid")
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or payload.get("identity") != expected_identity:
        raise CheckpointError("checkpoint_identity_mismatch")
    next_step = payload.get("next_step")
    if not isinstance(next_step, int) or not 0 <= next_step < step_limit:
        reason = "checkpoint_completed_result" if next_step == step_limit else "checkpoint_progress_invalid"
        raise CheckpointError(reason)
    for key in ("best_voice", "protected_preview_state", "python_rng", "numpy_rng", "torch_cpu_rng"):
        decode_bytes(payload.get(key))
    if payload.get("torch_cuda_rng") is not None:
        if not isinstance(payload["torch_cuda_rng"], list):
            raise CheckpointError("checkpoint_unsafe_state")
        for value in payload["torch_cuda_rng"]:
            decode_bytes(value)
    for key in ("improvements", "checkpoint_sequence"):
        if not isinstance(payload.get(key), int) or payload[key] < 0:
            raise CheckpointError("checkpoint_progress_invalid")
    for key in ("active_seconds", "live_pause_seconds"):
        if not isinstance(payload.get(key), (int, float)) or not math.isfinite(payload[key]) or payload[key] < 0:
            raise CheckpointError("checkpoint_progress_invalid")
    return payload


class ActiveBudget:
    def __init__(self, active_limit: float, wall_limit: float, *, active_elapsed: float = 0.0, pause_elapsed: float = 0.0, clock=time.monotonic):
        if not 60 <= active_limit <= 604_800 or not active_limit <= wall_limit <= 2_592_000:
            raise ValueError("build_budget_invalid")
        self.active_limit = active_limit
        self.wall_limit = wall_limit
        self.active_elapsed = active_elapsed
        self.pause_elapsed = pause_elapsed
        self.clock = clock
        self.wall_started = clock()
        self._active_started = self.wall_started

    def begin_pause(self) -> float:
        now = self.clock()
        self.active_elapsed += now - self._active_started
        return now

    def end_pause(self, started: float) -> None:
        now = self.clock()
        self.pause_elapsed += now - started
        self._active_started = now

    def enforce(self) -> None:
        now = self.clock()
        if now - self.wall_started >= self.wall_limit:
            raise TimeoutError("worker_wall_lifetime")
        if self.active_elapsed + now - self._active_started >= self.active_limit:
            raise TimeoutError("worker_active_budget")
