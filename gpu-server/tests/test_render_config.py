import copy
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "render-config.py"
SPEC = importlib.util.spec_from_file_location("render_config", MODULE_PATH)
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def manifest(**overrides):
    model = {
        "api_name": "heartcode-chat-nsfw",
        "kind": "chat",
        "min_replicas": 2,
        "model_type": "nsfw",
        "source": {"type": "gguf", "file": "model.gguf"},
        "deployments": [{"gpu": 4, "port": 8083}, {"gpu": 5, "port": 8084}],
    }
    model.update(overrides)
    return {"host": "192.0.2.1", "models": [model]}


def test_committed_manifest_is_valid():
    render.validate(render.load_manifest())


def test_every_committed_group_declares_min_replicas():
    for model in render.load_manifest()["models"]:
        assert "min_replicas" in model, model["api_name"]


def test_routed_count_at_minimum_passes():
    render.validate(manifest())


def test_removed_replica_below_minimum_fails_naming_group():
    data = manifest()
    data["models"][0]["deployments"].pop()
    with pytest.raises(render.ManifestError, match=r"heartcode-chat-nsfw: 1 routed deployment\(s\) is below min_replicas 2"):
        render.validate(data)


@pytest.mark.parametrize("value", [None, 0, -1, "2", 1.5, True])
def test_missing_or_invalid_min_replicas_fails(value):
    data = manifest(min_replicas=value)
    if value is None:
        del data["models"][0]["min_replicas"]
    with pytest.raises(render.ManifestError, match="heartcode-chat-nsfw: min_replicas must be an integer >= 1"):
        render.validate(data)


def test_check_fails_when_committed_manifest_drops_below_minimum(monkeypatch):
    data = render.load_manifest()
    broken = copy.deepcopy(data)
    group = next(m for m in broken["models"] if m["kind"] == "chat")
    group["deployments"] = group["deployments"][: group["min_replicas"] - 1]
    monkeypatch.setattr(render, "load_manifest", lambda: broken)
    assert render.main(["--check"]) == 1
