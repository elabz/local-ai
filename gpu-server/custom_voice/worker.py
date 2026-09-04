"""Restricted multi-reference KVoiceWalk pilot worker."""

from __future__ import annotations

import argparse
import base64
import io
import contextlib
import fcntl
import hashlib
import json
import os
import random
import resource
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

try:
    from custom_voice.build_runtime import (
        ActiveBudget, CheckpointError, PerformanceEvidence, decode_bytes, encode_bytes,
        load_checkpoint, score_candidate, should_stop_for_plateau,
        validate_plateau_policy, write_checkpoint,
    )
except ModuleNotFoundError:  # Standalone worker image entrypoint.
    from build_runtime import (  # type: ignore[no-redef]
        ActiveBudget, CheckpointError, PerformanceEvidence, decode_bytes, encode_bytes,
        load_checkpoint, score_candidate, should_stop_for_plateau,
        validate_plateau_policy, write_checkpoint,
    )

BUILDER_PROFILE = "kvoicewalk-multireference.v1"
BUILDER_REVISION = "3a38c6030cc4657df073c67ded37cdf7627c4969"
KOKORO_RUNTIME_IMAGE = "ghcr.io/remsky/kokoro-fastapi-gpu:v0.6.0@sha256:560e5ba33e78597cf35d266a5591c3ce7558dce318b3019fb6d94e28b466080b"


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("workspace_path_invalid")
    return Path(*candidate.parts)


def load_build_plan(plan_path: Path, workspace: Path) -> tuple[dict, list[tuple[str, Path, Path]]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("builder_profile") != BUILDER_PROFILE:
        raise ValueError("builder_profile_invalid")
    excluded = plan.get("excluded_adaptation_sample_ids", [])
    if not isinstance(excluded, list) or any(not isinstance(value, str) or not value for value in excluded):
        raise ValueError("excluded_samples_invalid")
    excluded_ids = set(excluded)
    if len(excluded_ids) != len(excluded):
        raise ValueError("excluded_samples_invalid")
    references: list[tuple[str, Path, Path]] = []
    adaptation_ids: set[str] = set()
    for sample in plan.get("samples", []):
        if sample.get("role") != "adaptation":
            continue
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError("sample_id_invalid")
        adaptation_ids.add(sample_id)
        if sample_id in excluded_ids:
            continue
        audio = workspace / _safe_relative(sample["audio_path"])
        transcript = workspace / _safe_relative(sample["transcript_path"])
        if not audio.is_file() or not transcript.is_file():
            raise ValueError("workspace_input_missing")
        references.append((sample_id, audio, transcript))
    if len(references) < 2:
        raise ValueError("adaptation_samples_insufficient")
    if not excluded_ids.issubset(adaptation_ids):
        raise ValueError("excluded_samples_invalid")
    return plan, references


def gpu_free_mib() -> int:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    if len(values) != 1:
        raise ValueError("gpu_visibility_invalid")
    return values[0]


def gpu_memory_mib() -> tuple[int, int]:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("gpu_visibility_invalid")
    try:
        total, free = (int(value.strip()) for value in rows[0].split(","))
    except (TypeError, ValueError) as error:
        raise ValueError("gpu_metrics_invalid") from error
    if total <= 0 or free < 0 or free > total:
        raise ValueError("gpu_metrics_invalid")
    return total, free


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


class ResourceObservations:
    """Checkpoint-sampled, content-free worker resource observations."""

    def __init__(self, workspace: Path, output: Path) -> None:
        self.workspace = workspace
        self.output = output
        self.peak_gpu_used_mib = 0
        self.minimum_gpu_free_mib: int | None = None
        self.peak_rss_mib = 0.0
        self.peak_private_bytes = 0

    def sample(self) -> None:
        total, free = gpu_memory_mib()
        self.peak_gpu_used_mib = max(self.peak_gpu_used_mib, total - free)
        self.minimum_gpu_free_mib = free if self.minimum_gpu_free_mib is None else min(self.minimum_gpu_free_mib, free)
        # ru_maxrss is KiB on the Linux worker image.
        self.peak_rss_mib = max(self.peak_rss_mib, float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024)
        self.peak_private_bytes = max(self.peak_private_bytes, _tree_bytes(self.workspace) + _tree_bytes(self.output))

    def result(self) -> dict[str, int | float]:
        if self.minimum_gpu_free_mib is None:
            raise ValueError("resource_observations_missing")
        return {
            "peak_observed_gpu_used_mib": self.peak_gpu_used_mib,
            "minimum_observed_gpu_free_mib": self.minimum_gpu_free_mib,
            "peak_worker_rss_mib": round(self.peak_rss_mib, 3),
            "peak_private_job_bytes": self.peak_private_bytes,
        }


def enforce_gpu_admission(min_free_mib: int) -> int:
    available = gpu_free_mib()
    if available < min_free_mib:
        raise RuntimeError("gpu_admission_deferred")
    return available


def enforce_runtime_reserve(min_free_mib: int) -> int:
    available = gpu_free_mib()
    if available < min_free_mib:
        raise RuntimeError("gpu_runtime_reserve_exhausted")
    return available


def enforce_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("worker_timeout")


def enforce_not_cancelled(cancel_path: Path) -> None:
    if cancel_path.exists():
        raise RuntimeError("worker_cancelled")


def enforce_live_health(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("live_speech_unhealthy")
    except (OSError, ValueError) as error:
        raise RuntimeError("live_speech_unhealthy") from error


def wait_for_inference_idle(url: str, deadline: float, *, required_idle_seconds: float = 5.0) -> None:
    while True:
        enforce_deadline(deadline)
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                value = json.loads(response.read(4096))
            active = int(value["active_requests"])
            idle = float(value["idle_seconds"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise RuntimeError("live_activity_unavailable") from error
        if active == 0 and idle >= required_idle_seconds:
            return
        time.sleep(min(1.0, max(0.1, required_idle_seconds - idle)))


def wait_for_inference_idle_budgeted(url: str, deadline: float, budget: ActiveBudget, evidence: PerformanceEvidence, *, required_idle_seconds: float = 5.0) -> None:
    paused = budget.begin_pause()
    started = time.monotonic()
    try:
        wait_for_inference_idle(url, deadline, required_idle_seconds=required_idle_seconds)
    finally:
        budget.end_pause(paused)
        evidence.add_duration("live_wait", time.monotonic() - started)


@contextmanager
def exclusive_worker(lock_path: Path):
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("worker_concurrency_exhausted") from error
        yield
    finally:
        os.close(descriptor)


def quiet_call(function, *args, **kwargs):
    """Contain third-party stdout/stderr that can expose paths or content."""

    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return function(*args, **kwargs)


def select_initial_population(selector, population_limit: int, runtime_reserve_mib: int, deadline: float, cancel_path: Path, live_activity_url: str):
    """Mirror KVoiceWalk selection with deterministic ordering and reserve checks."""

    voices = sorted(selector.voices, key=lambda item: item["name"])
    for voice in voices:
        enforce_not_cancelled(cancel_path)
        enforce_deadline(deadline)
        if live_activity_url:
            wait_for_inference_idle(live_activity_url, deadline)
        enforce_runtime_reserve(runtime_reserve_mib)
        audio = selector.speech_generator.generate_audio(selector.target_text, voice["voice"])
        enforce_runtime_reserve(runtime_reserve_mib)
        other_audio = selector.speech_generator.generate_audio(selector.other_text, voice["voice"])
        target_similarity = selector.fitness_scorer.target_similarity(audio)
        voice["results"] = selector.fitness_scorer.hybrid_similarity(
            audio, other_audio, target_similarity
        )

    selected = sorted(
        voices,
        key=lambda item: (-item["results"]["score"], item["name"]),
    )[:population_limit]
    return [voice["voice"] for voice in selected]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tensor_bytes(tensor) -> bytes:
    array = tensor.detach().to(device="cpu", dtype=tensor.new_empty((), device="cpu").float().dtype).contiguous().numpy()
    header = json.dumps({"dtype": str(array.dtype), "shape": list(array.shape)}, separators=(",", ":")).encode()
    return len(header).to_bytes(4, "big") + header + array.tobytes()


def _tensor_from_bytes(value: bytes, torch):
    import numpy as np
    if len(value) < 5:
        raise CheckpointError("checkpoint_unsafe_state")
    size = int.from_bytes(value[:4], "big")
    if size > 4096 or 4 + size > len(value):
        raise CheckpointError("checkpoint_unsafe_state")
    header = json.loads(value[4:4 + size])
    if header.get("dtype") != "float32" or not isinstance(header.get("shape"), list) or len(header["shape"]) > 4:
        raise CheckpointError("checkpoint_unsafe_state")
    expected = 4
    for dimension in header["shape"]:
        if not isinstance(dimension, int) or not 0 <= dimension <= 1_000_000:
            raise CheckpointError("checkpoint_unsafe_state")
        expected *= dimension
    raw = value[4 + size:]
    if len(raw) != expected:
        raise CheckpointError("checkpoint_unsafe_state")
    return torch.frombuffer(bytearray(raw), dtype=torch.float32).reshape(header["shape"]).clone()


def _pickle_rng(value) -> str:
    import pickle
    return encode_bytes(pickle.dumps(value, protocol=5))


def _unpickle_rng(value: str):
    # RNG payloads are integrity-bound worker output, but use a restricted unpickler.
    import pickle
    class RestrictedUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            raise CheckpointError("checkpoint_unsafe_state")
    return RestrictedUnpickler(io.BytesIO(decode_bytes(value))).load()


def _checkpoint_identity(plan: dict, plan_path: Path, worker_image_digest: str, device: str, backend: str) -> dict[str, object]:
    return {
        "manifest_sha256": plan["manifest_sha256"],
        "build_plan_sha256": _sha256(plan_path),
        "builder_profile": BUILDER_PROFILE,
        "builder_revision": BUILDER_REVISION,
        "worker_image_digest": worker_image_digest,
        "kokoro_model": "hexgrad/Kokoro-82M:v1.0",
        "kokoro_runtime_image": KOKORO_RUNTIME_IMAGE,
        "backend": backend,
        "device": device,
        "seed": int(plan["seed"]),
    }


def run_build(plan_path: Path, workspace: Path, output: Path) -> dict[str, object]:
    import numpy as np
    import soundfile as sf
    import torch
    from resemblyzer import VoiceEncoder, preprocess_wav
    from utilities.fitness_scorer import FitnessScorer
    from utilities.initial_selector import InitialSelector
    from utilities.voice_generator import VoiceGenerator
    from kokoro import KModel, KPipeline

    plan, references = load_build_plan(plan_path, workspace)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    if (output / "result.json").exists():
        raise ValueError("build_result_exists")
    worker_image_digest = os.environ.get("CUSTOM_VOICE_WORKER_IMAGE_DIGEST", "")
    if len(worker_image_digest) != 64 or any(character not in "0123456789abcdef" for character in worker_image_digest):
        raise ValueError("worker_image_digest_missing")
    seed = int(plan["seed"])
    active_work_budget_seconds = int(plan.get("active_work_budget_seconds", plan.get("max_duration_seconds", 21_600)))
    maximum_wall_lifetime_seconds = int(plan.get("maximum_wall_lifetime_seconds", active_work_budget_seconds))
    budget = ActiveBudget(active_work_budget_seconds, maximum_wall_lifetime_seconds)
    deadline = time.monotonic() + maximum_wall_lifetime_seconds
    cancel_path = output / "cancel.requested"
    live_health_url = os.environ.get("CUSTOM_VOICE_LIVE_HEALTH_URL", "")
    live_activity_url = os.environ.get("CUSTOM_VOICE_LIVE_ACTIVITY_URL", "")
    if plan.get("require_live_health", True) and not live_health_url:
        raise ValueError("live_health_url_missing")
    if live_health_url:
        enforce_live_health(live_health_url)
    if plan.get("require_live_activity", False) and not live_activity_url:
        raise ValueError("live_activity_url_missing")
    backend = str(plan.get("scoring_backend", "exhaustive_sequential"))
    if backend not in {"exhaustive_sequential", "early_rejection_sequential"}:
        raise ValueError("scoring_backend_invalid")
    backend_reason = "batch_unsupported" if plan.get("batch_backend_enabled", False) else "prepared_inputs_unsupported"
    evidence = PerformanceEvidence(backend, backend_reason)
    if plan.get("batch_backend_enabled", False):
        evidence.backend_fallbacks += 1
    if live_activity_url:
        wait_for_inference_idle_budgeted(live_activity_url, deadline, budget, evidence)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    min_free_mib = int(plan.get("min_free_vram_mib", 5_000))
    admitted_free_mib = enforce_gpu_admission(min_free_mib)
    runtime_reserve_mib = int(plan.get("runtime_free_vram_mib", 1_024))
    if runtime_reserve_mib < 512:
        raise ValueError("runtime_vram_reserve_invalid")
    device = str(plan.get("device", "cuda"))
    identity = _checkpoint_identity(plan, plan_path, worker_image_digest, device, backend)
    resources = ResourceObservations(workspace, output)
    resources.sample()
    encoder = VoiceEncoder(device=device)

    embeddings = []
    feature_sets = []
    reference_texts = []
    feature_extractor = object.__new__(FitnessScorer)
    for _, audio_path, transcript_path in references:
        waveform = preprocess_wav(str(audio_path), source_sr=24_000)
        embedding = encoder.embed_utterance(waveform)
        norm = np.linalg.norm(embedding)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("speaker_embedding_invalid")
        embeddings.append(embedding / norm)
        decoded, _ = sf.read(audio_path, dtype="float32")
        feature_sets.append(feature_extractor.extract_features(decoded))
        text = transcript_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("transcript_empty")
        reference_texts.append(text)

    centroid = np.mean(np.stack(embeddings), axis=0)
    centroid /= np.linalg.norm(centroid)
    target_features = {
        key: float(np.mean([features[key] for features in feature_sets]))
        for key in feature_sets[0]
    }

    scorer = object.__new__(FitnessScorer)
    scorer.device = device
    scorer.encoder = encoder
    scorer.target_embed = centroid
    scorer.target_features = target_features

    model = quiet_call(
        KModel,
        repo_id="hexgrad/Kokoro-82M",
        config="/app/api/src/models/v1_0/config.json",
        model="/app/api/src/models/v1_0/kokoro-v1_0.pth",
    ).to(device).eval()
    pipeline = quiet_call(
        KPipeline,
        lang_code="a",
        repo_id="hexgrad/Kokoro-82M",
        model=model,
        device=device,
    )

    class LocalSpeechGenerator:
        def generate_audio(self, text: str, voice, speed: float = 1.0):
            voice_arg = voice.detach().to(device="cpu", dtype=torch.float32) if torch.is_tensor(voice) else voice
            chunks = [audio for _, _, audio in pipeline(text, voice=voice_arg, speed=speed)]
            return np.concatenate(chunks).astype(np.float32) if chunks else np.array([], dtype=np.float32)

    speech_generator = LocalSpeechGenerator()

    import utilities.initial_selector as selector_module

    selector_module.FitnessScorer = lambda *_args, **_kwargs: scorer
    selector_module.SpeechGenerator = lambda *_args, **_kwargs: speech_generator
    other_text = str(plan.get("stability_text", "Stable voices remain clear across different sentences and speaking rhythms."))
    selector = quiet_call(
        InitialSelector,
        str(references[0][1]),
        reference_texts[0],
        other_text,
        voice_folder=str(plan.get("voice_folder", "/opt/kvoicewalk/voices")),
        device=device,
    )
    population = select_initial_population(
        selector,
        int(plan.get("population_limit", 10)),
        runtime_reserve_mib,
        deadline,
        cancel_path,
        live_activity_url,
    )
    if live_health_url:
        enforce_live_health(live_health_url)
    if live_activity_url:
        wait_for_inference_idle(live_activity_url, deadline)
    voice_generator = VoiceGenerator(population, None, device=device)

    fitness_text_count = int(plan.get("fitness_text_count", 2))
    if not 2 <= fitness_text_count <= min(4, len(reference_texts)):
        raise ValueError("fitness_text_count_invalid")

    def score(voice, text_offset: int, minimum: float = 0.0):
        texts = [reference_texts[(text_offset + offset) % len(reference_texts)] for offset in range(fitness_text_count)]
        def synthesize(text, candidate):
            budget.enforce()
            if live_activity_url:
                wait_for_inference_idle_budgeted(live_activity_url, deadline, budget, evidence)
            enforce_runtime_reserve(runtime_reserve_mib)
            started = time.monotonic()
            audio = speech_generator.generate_audio(text, candidate)
            evidence.add_duration("synthesis", time.monotonic() - started)
            return audio
        def similarity(audio):
            started = time.monotonic()
            value = scorer.target_similarity(audio)
            evidence.add_duration("speaker_encoding", time.monotonic() - started)
            return value
        def hybrid(first, second, target):
            started = time.monotonic()
            value = scorer.hybrid_similarity(first, second, target)
            evidence.add_duration("hybrid_scoring", time.monotonic() - started)
            return value
        return score_candidate(
            voice, texts, minimum, synthesize, similarity, hybrid,
            early_rejection=backend == "early_rejection_sequential", evidence=evidence,
        )

    steps = int(plan.get("step_limit", 10_000))
    checkpoint_interval = int(plan.get("checkpoint_interval", 100))
    plateau_policy = validate_plateau_policy(plan.get("plateau_policy"), steps)
    checkpoint_path = output / "checkpoint.v2.json"
    legacy_checkpoint = output / "checkpoint.pt"
    if legacy_checkpoint.exists() and not checkpoint_path.exists():
        raise CheckpointError("checkpoint_legacy_non_resumable")
    best_voice = voice_generator.starting_voice
    best = None
    next_step = 0
    started = time.monotonic()
    improvements = 0
    checkpoint_sequence = 0
    last_improvement_step = 0
    if checkpoint_path.exists():
        resumed = load_checkpoint(checkpoint_path, identity, steps)
        best_voice = _tensor_from_bytes(decode_bytes(resumed["best_voice"]), torch).to(device)
        best = dict(resumed["best_score"])
        best["audio"] = _tensor_from_bytes(decode_bytes(resumed["protected_preview_state"]), torch).numpy()
        next_step = resumed["next_step"]
        improvements = resumed["improvements"]
        checkpoint_sequence = resumed["checkpoint_sequence"]
        last_improvement_step = int(resumed.get("last_improvement_step", 0))
        budget.active_elapsed = float(resumed["active_seconds"])
        budget.pause_elapsed = float(resumed["live_pause_seconds"])
        random.setstate(_unpickle_rng(resumed["python_rng"]))
        numpy_state = json.loads(decode_bytes(resumed["numpy_rng"]).decode())
        np.random.set_state((numpy_state["name"], np.asarray(numpy_state["keys"], dtype=np.uint32), numpy_state["pos"], numpy_state["has_gauss"], numpy_state["cached_gaussian"]))
        torch.set_rng_state(torch.frombuffer(bytearray(decode_bytes(resumed["torch_cpu_rng"])), dtype=torch.uint8).clone())
        if torch.cuda.is_available() and resumed.get("torch_cuda_rng"):
            torch.cuda.set_rng_state_all([torch.frombuffer(bytearray(decode_bytes(value)), dtype=torch.uint8).clone() for value in resumed["torch_cuda_rng"]])
        evidence.resumes += 1
    else:
        best = score(best_voice, 0)

    def save_progress(next_uncompleted_step: int) -> None:
        nonlocal checkpoint_sequence
        checkpoint_sequence += 1
        numpy_state = np.random.get_state()
        numpy_payload = {"name": numpy_state[0], "keys": numpy_state[1].tolist(), "pos": numpy_state[2], "has_gauss": numpy_state[3], "cached_gaussian": numpy_state[4]}
        active_now = budget.active_elapsed + time.monotonic() - budget._active_started
        payload = {
            "identity": identity,
            "next_step": next_uncompleted_step,
            "improvements": improvements,
            "checkpoint_sequence": checkpoint_sequence,
            "last_improvement_step": last_improvement_step,
            "active_seconds": active_now,
            "live_pause_seconds": budget.pause_elapsed,
            "best_voice": encode_bytes(_tensor_bytes(best_voice)),
            "best_score": {"score": float(best["score"]), "target_similarity": float(best["target_similarity"])},
            "protected_preview_state": encode_bytes(_tensor_bytes(torch.from_numpy(np.asarray(best["audio"], dtype=np.float32)))),
            "python_rng": _pickle_rng(random.getstate()),
            "numpy_rng": encode_bytes(json.dumps(numpy_payload, separators=(",", ":")).encode()),
            "torch_cpu_rng": encode_bytes(bytes(torch.get_rng_state().tolist())),
            "torch_cuda_rng": [encode_bytes(bytes(value.tolist())) for value in torch.cuda.get_rng_state_all()] if torch.cuda.is_available() else [],
        }
        checkpoint_started = time.monotonic()
        write_checkpoint(checkpoint_path, payload)
        evidence.add_duration("checkpoint_write", time.monotonic() - checkpoint_started)
        evidence.checkpoints += 1

    stop_reason = "step_limit"
    try:
        step_iterator = range(next_step, steps)
        for step in step_iterator:
            budget.enforce()
            enforce_not_cancelled(cancel_path)
            if live_health_url and step % checkpoint_interval == 0:
                enforce_live_health(live_health_url)
            if live_activity_url:
                wait_for_inference_idle_budgeted(live_activity_url, deadline, budget, evidence)
            enforce_runtime_reserve(runtime_reserve_mib)
            diversity = random.uniform(0.01, 0.15)
            candidate = voice_generator.generate_voice(best_voice, diversity, device=device)
            candidate_result = score(candidate, step % len(reference_texts), best["target_similarity"] * 0.98)
            if candidate_result["score"] > best["score"]:
                best_voice = candidate
                best = candidate_result
                improvements += 1
                last_improvement_step = step + 1
            evidence.executed_steps = step + 1
            if (step + 1) % checkpoint_interval == 0 and step + 1 < steps:
                save_progress(step + 1)
                resources.sample()
                print(json.dumps({"event": "build_progress", "executed_steps": step + 1, "step_limit": steps, "performance": evidence.result()}, sort_keys=True), flush=True)
            if should_stop_for_plateau(plateau_policy, step + 1, last_improvement_step):
                stop_reason = "plateau"
                break
    except TimeoutError as error:
        stop_reason = str(error)
        if evidence.executed_steps < steps:
            save_progress(evidence.executed_steps)
        raise

    artifact = output / "artifact.pt"
    preview = output / "preview.wav"
    torch.save(best_voice.detach().cpu(), artifact)
    sf.write(preview, best["audio"], 24_000)
    artifact.chmod(0o600)
    preview.chmod(0o600)
    resources.sample()
    result = {
        "schema_version": "custom-voice-build-result.v1",
        "builder_profile": BUILDER_PROFILE,
        "builder_revision": BUILDER_REVISION,
        "worker_image_digest": worker_image_digest,
        "kokoro_runtime_image": KOKORO_RUNTIME_IMAGE,
        "build_plan_sha256": _sha256(plan_path),
        "manifest_sha256": plan["manifest_sha256"],
        "seed": seed,
        "adaptation_sample_ids": [sample_id for sample_id, _, _ in references],
        "excluded_adaptation_sample_ids": sorted(set(plan.get("excluded_adaptation_sample_ids", []))),
        "fitness_text_count": fitness_text_count,
        "artifact_sha256": _sha256(artifact),
        "artifact_size": artifact.stat().st_size,
        "preview_sha256": _sha256(preview),
        "steps": evidence.executed_steps,
        "target_steps": steps,
        "improvements": improvements,
        "score": float(best["score"]),
        "target_similarity": float(best["target_similarity"]),
        "duration_seconds": time.monotonic() - started,
        "active_work_seconds": budget.active_elapsed + time.monotonic() - budget._active_started,
        "live_pause_seconds": budget.pause_elapsed,
        "maximum_wall_lifetime_seconds": maximum_wall_lifetime_seconds,
        "stop_reason": stop_reason,
        "plateau_policy": plateau_policy,
        "performance_evidence": evidence.result(),
        "admitted_free_vram_mib": admitted_free_mib,
        "runtime_free_vram_reserve_mib": runtime_reserve_mib,
        "resource_observations": resources.result(),
    }
    result_path = output / "result.json"
    result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    result_path.chmod(0o600)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        lock_path = Path(os.environ.get("CUSTOM_VOICE_GPU_LOCK", "/data/custom-voice-locks/speech-gpu.lock"))
        with exclusive_worker(lock_path):
            result = run_build(arguments.plan, arguments.workspace, arguments.output)
        print(json.dumps({"outcome": "succeeded", "artifact_sha256": result["artifact_sha256"]}))
    except Exception as error:
        code = str(error) if str(error).replace("_", "").isalnum() else "worker_failed"
        outcome = "cancelled" if code == "worker_cancelled" else "failed"
        if code != "build_result_exists":
            for name in ("artifact.pt", "preview.wav", "result.json"):
                partial = arguments.output / name
                if partial.exists() and partial.is_file():
                    partial.unlink()
        if outcome == "cancelled":
            checkpoint = arguments.output / "checkpoint.pt"
            if checkpoint.exists() and checkpoint.is_file():
                checkpoint.unlink()
        print(json.dumps({"outcome": outcome, "reason": code, "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
