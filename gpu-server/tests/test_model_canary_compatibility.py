import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/model_canary_compatibility.py"
SPEC = importlib.util.spec_from_file_location("model_canary_compatibility", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_retrieval_prompt_places_all_markers_in_order():
    prompt = module.synthetic_retrieval_prompt(20)
    positions = [prompt.index(marker) for marker in module.MARKERS]
    assert positions == sorted(positions)
    assert len(set(positions)) == 3


def test_schema_is_closed_and_requires_all_fields():
    value = module.schema("probe", {"status": {"type": "string"}}, ["status"])
    body = value["json_schema"]["schema"]
    assert body["additionalProperties"] is False
    assert body["required"] == ["status"]


def test_content_object_rejects_non_object():
    try:
        module.content_object({"choices": [{"message": {"content": "[]"}}]})
    except ValueError as error:
        assert "not an object" in str(error)
    else:
        raise AssertionError("non-object content was accepted")


def test_visible_thought_channel_is_a_reasoning_leak():
    value = {"choices": [{"message": {"content": "<|channel>thought\nREADY"}}]}
    assert module.reasoning_leaked(value)
