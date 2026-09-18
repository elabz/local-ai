import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "model_canary_blind_packet.py"
spec = importlib.util.spec_from_file_location("model_canary_blind_packet", SCRIPT)
assert spec is not None and spec.loader is not None
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


def test_style_checks_strong_persona_rules():
    checks = {"max_sentences": 3, "forbid_contractions": True, "require_substring": "recruit"}
    good = "You are late, recruit. Explain yourself. Then run."
    bad = "You're late. I don't care why. Explain. Then run five laps, recruit."
    assert all(packet.style_checks(checks, 0, good).values())
    result = packet.style_checks(checks, 0, bad)
    assert result["forbid_contractions"] is False
    assert result["max_sentences"] is False
    assert result["require_substring"] is True


def test_style_checks_dialogue_only_rejects_narration():
    checks = {"dialogue_only": True}
    assert packet.style_checks(checks, 0, '"Evening."\n"What will it be?"')["dialogue_only"]
    assert not packet.style_checks(checks, 0, '*wipes the bar* "Evening."')["dialogue_only"]
    assert not packet.style_checks(checks, 0, "")["dialogue_only"]


def test_style_checks_descriptive_and_lore_by_turn():
    checks = {"min_paragraphs": 2, "forbid_quotes": True,
              "require_all_substrings": ["Ashe"], "require_all_substrings_turn2": ["north"]}
    prose = "Light spills over the ridge and Ashe hangs low.\n\nThe path bends north toward the pass."
    first = packet.style_checks(checks, 0, prose)
    assert first["min_paragraphs"] and first["forbid_quotes"] and first["require_all_substrings"]
    assert "require_all_substrings_turn2" not in first
    second = packet.style_checks(checks, 1, "They walk north.")
    assert second["require_all_substrings_turn2"] is True
    assert second["min_paragraphs"] is False
    assert not packet.style_checks({"forbid_quotes": True}, 0, 'She said "no".')["forbid_quotes"]


def test_summarize_counts_per_blind_label():
    cases = [{
        "case_id": "x", "category": "y",
        "arms": {
            "A": [{"blank": False, "reasoning_nonempty": False, "visible_reasoning_marker": False,
                   "style_checks": {"a": True, "b": False}}],
            "B": [{"blank": True, "reasoning_nonempty": True, "visible_reasoning_marker": False,
                   "style_checks": {}}],
        },
    }]
    summary = packet.summarize(cases)
    assert summary["A"] == {"turns": 1, "blank": 0, "reasoning_leaks": 0, "style_checks": 2, "style_checks_passed": 1}
    assert summary["B"] == {"turns": 1, "blank": 1, "reasoning_leaks": 1, "style_checks": 0, "style_checks_passed": 0}


def test_build_writes_private_prose_and_public_hashes_only(tmp_path, monkeypatch):
    corpus = {"version": "t", "cases": [{
        "id": "c1", "category": "cat",
        "card": {"name": "N", "persona": "P", "greeting": "G"},
        "script": [{"user": "hello"}], "checks": {"min_characters": 1},
    }]}
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus))
    identity = tmp_path / "id.json"
    identity.write_text(json.dumps({"model_file": "m.gguf"}))
    replies = {"http://challenger": "secret challenger prose", "http://control": "secret control prose"}

    def fake_request(url, payload, timeout):
        return {"choices": [{"message": {"content": replies[url]}}], "timings": {"predicted_per_second": 20.0}}

    monkeypatch.setattr(packet, "request_json", fake_request)

    class Args:
        challenger_url = "http://challenger"
        control_url = "http://control"
        challenger_identity = str(identity)
        control_identity = str(identity)
        corpus = str(corpus_path)
        cases = "c1"
        seed = 1
        timeout = 1.0
        max_tokens = 8
        temperature = 1.0
        top_p = 0.95
        top_k = 64
        min_p = 0.0
        repeat_penalty = 1.0

    private, public = packet.build(Args())
    assignment = private["answer_key"]["c1"]
    assert sorted(assignment.values()) == ["A", "B"]
    public_text = json.dumps(public)
    assert "secret" not in public_text
    assert "answer_key_sha256" in public and "answer_key" not in public
    label = assignment["challenger"]
    assert private["cases"][0]["transcripts"][label][0]["content"] == "secret challenger prose"
    assert public["cases"][0]["arms"][label][0]["sha256"] == packet.sha256_text("secret challenger prose")
    assert public["summary"][label]["style_checks_passed"] == 1


def test_build_rejects_unknown_case(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps({"version": "t", "cases": []}))
    identity = tmp_path / "id.json"
    identity.write_text("{}")

    class Args:
        challenger_url = control_url = "http://x"
        challenger_identity = control_identity = str(identity)
        corpus = str(corpus_path)
        cases = "missing"
        seed = 1
        timeout = 1.0
        max_tokens = 8
        temperature = top_p = 1.0
        top_k = 64
        min_p = 0.0
        repeat_penalty = 1.0

    with pytest.raises(RuntimeError):
        packet.build(Args())
