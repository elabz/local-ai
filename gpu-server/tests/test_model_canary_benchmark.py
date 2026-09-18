import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/model_canary_benchmark.py"
SPEC = importlib.util.spec_from_file_location("model_canary_benchmark", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_percentile_interpolates_p10():
    assert module.percentile([10.0, 20.0], 0.1) == 11.0


def test_sfw_gate_requires_16k_and_p10_floor():
    assert not module.gate("sfw", 8192, [20.0] * 10, 0)["passed"]
    assert module.gate("sfw", 16384, [10.0] * 10, 0)["passed"]
    assert not module.gate("sfw", 16384, [9.9] * 10, 0)["passed"]


def test_nsfw_gate_uses_12_tps_floor_and_fails_closed():
    assert module.gate("nsfw", 8192, [12.0] * 10, 0)["passed"]
    assert not module.gate("nsfw", 8192, [20.0] * 10, 1)["passed"]


def test_context_plan_is_progressive():
    assert module.context_plan(16384) == [4096, 8192, 16384]
    assert module.context_plan(32768) == [4096, 8192, 16384, 24576, 32768]


def test_identity_redacts_unknown_and_private_fields():
    value = module.safe_identity({"model_repo": "repo", "model_sha256": "abc", "prompt": "private", "token": "secret"})
    assert value == {"model_repo": "repo", "model_sha256": "abc"}


def test_nsfw_gate_does_not_require_json_schema_semantics():
    assert module.gate("nsfw", 16384, [23.0] * 10, 0)["passed"]
