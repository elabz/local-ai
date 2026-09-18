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


def test_committed_claude_md_tables_are_in_sync():
    current = render.OUT_CLAUDE.read_text()
    assert render.render_claude_md(render.load_manifest(), current) == current


def test_hand_edited_claude_md_row_fails_check_naming_the_file(tmp_path, monkeypatch, capsys):
    rendered = render.render_claude_md(render.load_manifest(), render.OUT_CLAUDE.read_text())
    row = "| `heartcode-image` | Image | 8 | 1 (1) |"
    assert row in rendered
    edited = tmp_path / "CLAUDE.md"
    edited.write_text(rendered.replace(row, "| `heartcode-image` | Image | 7-8 | 2 (1) |", 1))
    monkeypatch.setattr(render, "OUT_CLAUDE", edited)

    assert render.main(["--check"]) == 1
    assert f"DRIFT: {edited} is out of sync" in capsys.readouterr().err


def test_generator_rewrites_only_inside_the_markers():
    prose = "# Title\n\nHand-written prose, untouched.\n\n"
    text = (
        prose
        + "<!-- BEGIN GENERATED: models -->\nstale\n<!-- END GENERATED: models -->"
        + "\n\nMiddle prose.\n\n"
        + "<!-- BEGIN GENERATED: ports -->\n<!-- END GENERATED: ports -->\n\nTail.\n"
    )
    out = render.render_claude_md(manifest(litellm_model="model.gguf"), text)
    assert out.startswith(prose + "<!-- BEGIN GENERATED: models -->\n")
    assert "stale" not in out
    assert "\n<!-- END GENERATED: models -->\n\nMiddle prose.\n\n<!-- BEGIN GENERATED: ports -->\n" in out
    assert out.endswith("<!-- END GENERATED: ports -->\n\nTail.\n")
    assert "| 8083-8084 | `heartcode-chat-nsfw` |" in out


def test_missing_markers_fail():
    with pytest.raises(render.ManifestError, match="BEGIN GENERATED: models"):
        render.render_claude_md(manifest(), "no markers here\n")


@pytest.mark.parametrize(
    "filename,quant",
    [
        ("Llama-3.1-8B-Stheno-v3.4-Q5_K_M.gguf", "Q5_K_M"),
        ("Lumimaid-v0.2-8B-Q5_K_M-imat.gguf", "Q5_K_M"),
        ("nomic-embed-text-v1.5.Q8_0.gguf", "Q8_0"),
        ("model-IQ4_XS.gguf", "IQ4_XS"),
        ("no-tag.gguf", "—"),
    ],
)
def test_quant_is_read_from_the_gguf_filename(filename, quant):
    assert render._doc_quant({"source": {"file": filename}}) == quant


def test_invalid_docs_key_fails():
    with pytest.raises(render.ManifestError, match="docs must map"):
        render.validate(manifest(docs={"model": "x", "colour": "blue"}))
