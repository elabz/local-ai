import json
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.build_runtime import (
    ActiveBudget, CheckpointError, PerformanceEvidence, PreparedInputCache, load_checkpoint,
    score_candidate, should_stop_for_plateau, validate_plateau_policy,
    validate_safe_telemetry, write_checkpoint, select_batch_backend,
)


def scorer(similarities, *, early=True, floor=0.5):
    generated = []
    values = iter(similarities)
    result = score_candidate(
        "voice", ["one", "two", "three"], floor,
        lambda text, voice: generated.append(text) or text,
        lambda audio: next(values),
        lambda first, second, similarity: {"score": similarity + 0.1},
        early_rejection=early,
    )
    return result, generated


@pytest.mark.parametrize("values,count,position", [
    ([0.5, 0.9, 0.9], 1, 1), ([0.8, 0.5, 0.9], 2, 2), ([0.8, 0.7, 0.5], 3, 3),
])
def test_early_rejection_at_each_position_and_equality(values, count, position):
    result, generated = scorer(values)
    assert result["score"] == 0.0
    assert result["rejected_at"] == position
    assert len(generated) == count


def test_passing_candidate_evaluates_all_texts_and_hybrid_score():
    result, generated = scorer([0.8, 0.7, 0.6])
    assert result["target_similarity"] == 0.6
    assert result["score"] == pytest.approx(0.7)
    assert len(generated) == 3


def test_exhaustive_and_optimized_seeded_walk_select_same_best_with_savings():
    values = [[0.8, 0.7, 0.6], [0.4, 0.99, 0.99], [0.75, 0.74, 0.73], [0.72, 0.2, 0.9]]
    def walk(early):
        random.seed(137)
        best = {"score": 0.0, "target_similarity": 0.0}
        improvements = 0
        utterances = 0
        states = []
        for candidate, candidate_values in enumerate(values):
            floor = best["target_similarity"] * 0.98
            result, generated = scorer(candidate_values, early=early, floor=floor)
            utterances += len(generated)
            random.random()
            states.append(random.getstate())
            if result["score"] > best["score"]:
                best = result
                improvements += 1
        return best, improvements, utterances, states
    exhaustive = walk(False)
    optimized = walk(True)
    assert optimized[:2] == exhaustive[:2]
    assert optimized[2] < exhaustive[2]
    assert optimized[3] == exhaustive[3]


def test_nonfinite_similarity_fails_closed_and_ties_do_not_replace_best():
    with pytest.raises(ValueError, match="candidate_similarity_invalid"):
        scorer([float("nan"), 0.8, 0.8])
    result, _ = scorer([0.8, 0.8, 0.8])
    best = {"score": result["score"]}
    assert not result["score"] > best["score"]


@pytest.mark.parametrize("field", ["transcript", "transcript_hash", "audio", "credential", "host_path", "preview_id"])
def test_telemetry_rejects_protected_fields(field):
    with pytest.raises(ValueError, match="telemetry_protected_field"):
        validate_safe_telemetry({field: 1})


def checkpoint_payload(identity):
    import base64
    encoded = base64.b64encode(b"state").decode()
    return {
        "identity": identity, "next_step": 4, "improvements": 2,
        "checkpoint_sequence": 1, "active_seconds": 10.0, "live_pause_seconds": 2.0,
        "best_voice": encoded, "python_rng": encoded, "numpy_rng": encoded,
        "torch_cpu_rng": encoded, "torch_cuda_rng": [], "best_score": {"score": 0.7},
        "protected_preview_state": encoded,
    }


def test_checkpoint_is_atomic_restricted_integrity_and_identity_bound(tmp_path):
    path = tmp_path / "checkpoint.v2.json"
    identity = {"manifest": "a" * 64, "plan": "b" * 64, "builder": "revision", "image": "c" * 64, "model": "kokoro", "runtime": "v0.6.0", "backend": "early_rejection_sequential", "device": "cuda", "seed": 137}
    write_checkpoint(path, checkpoint_payload(identity))
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_checkpoint(path, identity, 10)["next_step"] == 4
    damaged = json.loads(path.read_text())
    damaged["payload"]["next_step"] = 5
    path.write_text(json.dumps(damaged))
    with pytest.raises(CheckpointError, match="checkpoint_integrity_invalid"):
        load_checkpoint(path, identity, 10)


def test_legacy_and_mismatched_checkpoints_fail_closed(tmp_path):
    path = tmp_path / "checkpoint.pt"
    path.write_bytes(b"legacy tensor")
    with pytest.raises(CheckpointError, match="checkpoint_corrupt"):
        load_checkpoint(path, {}, 10)
    path = tmp_path / "checkpoint.v2.json"
    write_checkpoint(path, checkpoint_payload({"seed": 1}))
    with pytest.raises(CheckpointError, match="checkpoint_identity_mismatch"):
        load_checkpoint(path, {"seed": 2}, 10)


def test_plateau_is_explicit_and_disabled_by_default():
    assert validate_plateau_policy(None, 6000) is None
    assert should_stop_for_plateau(None, 6000, 0) is False
    policy = validate_plateau_policy({"name": "plateau.v1", "minimum_step": 100, "consecutive_no_improvement": 50}, 6000)
    assert should_stop_for_plateau(policy, 149, 99) is True


def test_active_budget_excludes_live_pause_but_wall_limit_remains():
    now = [0.0]
    budget = ActiveBudget(60, 120, clock=lambda: now[0])
    now[0] = 10
    pause = budget.begin_pause()
    now[0] = 50
    budget.end_pause(pause)
    now[0] = 99
    budget.enforce()
    assert budget.active_elapsed == 10
    now[0] = 121
    with pytest.raises(TimeoutError, match="worker_wall_lifetime"):
        budget.enforce()


def test_performance_evidence_is_bounded_and_content_free():
    evidence = PerformanceEvidence("early_rejection_sequential", "batch_unsupported")
    evidence.add_duration("synthesis", 1.25)
    evidence.reject(2)
    evidence.utterances = 2
    assert evidence.result()["rejection_positions"] == {"2": 1}


def test_prepared_input_cache_is_build_local_equivalent_and_clearable():
    calls = []
    cache = PreparedInputCache(lambda value: calls.append(value) or tuple(value.encode()))
    first = cache.get("private words", "kokoro-a")
    assert cache.get("private words", "kokoro-a") == first
    assert calls == ["private words"]
    assert "private words" not in repr(cache.__dict__.keys())
    cache.clear()
    cache.get("private words", "kokoro-a")
    assert len(calls) == 2
    unsupported = PreparedInputCache(None)
    with pytest.raises(ValueError, match="prepared_inputs_unsupported"):
        unsupported.get("private words", "kokoro-a")


def test_batch_backend_requires_repeatable_equivalence_speed_and_vram():
    sequential = lambda: {"waveform_valid": True, "decisions": [False, True], "ordering": [1, 0], "duration_seconds": 2.0, "peak_gpu_used_mib": 1000}
    batch = lambda: {"waveform_valid": True, "decisions": [False, True], "ordering": [1, 0], "duration_seconds": 1.0, "peak_gpu_used_mib": 1200}
    assert select_batch_backend(sequential, batch, minimum_speedup=1.2, reserve_mib=1500) == ("batch_within_candidate", "none")
    assert select_batch_backend(sequential, None, minimum_speedup=1.2, reserve_mib=1500)[1] == "batch_unsupported"
    assert select_batch_backend(sequential, batch, minimum_speedup=3.0, reserve_mib=1500)[1] == "batch_performance_failed"
    assert select_batch_backend(sequential, batch, minimum_speedup=1.2, reserve_mib=1100)[1] == "batch_vram_reserve_failed"


@pytest.mark.parametrize("boundary", [2, 5, 8])
def test_seeded_walk_resume_matches_uninterrupted_at_multiple_boundaries(tmp_path, boundary):
    identity = {"seed": 137}
    def run(start, state=None):
        generator = random.Random(137)
        best = -1.0
        improvements = 0
        if state:
            generator.setstate(state[0]); best = state[1]; improvements = state[2]
        for step in range(start, 10):
            candidate = generator.random()
            if candidate > best:
                best = candidate; improvements += 1
            if step + 1 == boundary and state is None:
                return generator.getstate(), best, improvements
        return best, improvements, generator.getstate()
    interrupted = run(0)
    resumed = run(boundary, interrupted)
    full_boundary = boundary
    boundary = 11  # disable interruption for authoritative run
    uninterrupted = run(0)
    boundary = full_boundary
    assert resumed == uninterrupted


def test_repeated_pause_accounting_does_not_consume_active_budget():
    now = [0.0]
    budget = ActiveBudget(60, 300, clock=lambda: now[0])
    for active, paused in ((5, 20), (7, 30), (8, 40)):
        now[0] += active
        marker = budget.begin_pause()
        now[0] += paused
        budget.end_pause(marker)
    budget.enforce()
    assert budget.active_elapsed == 20
    assert budget.pause_elapsed == 90
