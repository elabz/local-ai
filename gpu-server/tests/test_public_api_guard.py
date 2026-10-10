"""litellm/public_api_guard.py: bounds on HeartCode's public API keys.

Runs without litellm installed: the guard falls back to a plain base class,
and its hooks are called directly with the dict shapes LiteLLM passes.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException

LITELLM_DIR = Path(__file__).resolve().parents[2] / "litellm"
sys.path.insert(0, str(LITELLM_DIR))

import public_api_guard as guard

PUBLIC = SimpleNamespace(metadata={"heartcode_key_name": "ST", "user_id": "u1"})
FIRST_PARTY = SimpleNamespace(metadata={"env": "production", "owner": "heartcode"})


def _guard(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return guard.PublicApiGuard()


def _chat(**extra):
    return {
        "model": "heartcode-chat-sfw",
        "messages": [{"role": "user", "content": "hi"}],
        "litellm_call_id": extra.pop("call_id", "call-1"),
        **extra,
    }


def _pre(g, data, key=PUBLIC, call_type="acompletion"):
    return asyncio.run(g.async_pre_call_hook(key, None, data, call_type))


def test_first_party_traffic_is_untouched(monkeypatch):
    g = _guard(monkeypatch)
    data = _chat(temperature=9.0, messages=[{"role": "user", "content": "x"}] * 500)

    assert _pre(g, data, key=FIRST_PARTY)["temperature"] == 9.0
    assert g.gate.in_flight("heartcode-chat-sfw") == 0


def test_embeddings_are_not_gated(monkeypatch):
    g = _guard(monkeypatch)
    data = {"model": "heartcode-embed", "input": "x" * 100_000}
    assert _pre(g, data, call_type="aembedding") is data


def test_too_many_messages_is_413(monkeypatch):
    g = _guard(monkeypatch)
    with pytest.raises(HTTPException) as err:
        _pre(g, _chat(messages=[{"role": "user", "content": "x"}] * 101))
    assert err.value.status_code == 413


def test_oversized_message_is_413_counting_bytes_not_characters(monkeypatch):
    g = _guard(monkeypatch)
    # 11,000 three-byte characters: under 32 KiB as characters, over as bytes.
    with pytest.raises(HTTPException) as err:
        _pre(g, _chat(messages=[{"role": "system", "content": "€" * 11_000}]))
    assert err.value.status_code == 413


def test_list_content_is_measured_by_its_text_parts(monkeypatch):
    g = _guard(monkeypatch)
    content = [{"type": "text", "text": "x" * 40_000}]
    with pytest.raises(HTTPException):
        _pre(g, _chat(messages=[{"role": "user", "content": content}]))


def test_samplers_are_clamped_and_absent_ones_stay_absent(monkeypatch):
    g = _guard(monkeypatch)
    data = _pre(
        g,
        _chat(temperature=5, top_p=1.5, top_k=10_000, min_p=-1, presence_penalty=-9, n=4),
    )

    assert data["temperature"] == 2.0
    assert data["top_p"] == 1.0
    assert data["top_k"] == 200 and isinstance(data["top_k"], int)
    assert data["min_p"] == 0.0
    assert data["presence_penalty"] == -2.0
    assert data["n"] == 1
    assert "frequency_penalty" not in data


def test_max_tokens_has_a_ceiling_even_when_unsent(monkeypatch):
    g = _guard(monkeypatch, PUBLIC_API_MAX_TOKENS="1024")
    assert _pre(g, _chat(call_id="a"))["max_tokens"] == 1024
    g.gate.release("a")
    assert _pre(g, _chat(call_id="b", max_tokens=99_999))["max_tokens"] == 1024
    g.gate.release("b")
    assert _pre(g, _chat(call_id="c", max_tokens=300))["max_tokens"] == 300


@pytest.mark.parametrize("bad", ["0.7", True, float("nan"), float("inf")])
def test_non_numeric_sampler_is_400(monkeypatch, bad):
    g = _guard(monkeypatch)
    with pytest.raises(HTTPException) as err:
        _pre(g, _chat(temperature=bad))
    assert err.value.status_code == 400


def test_admission_caps_each_model_group(monkeypatch):
    g = _guard(monkeypatch, PUBLIC_API_PARALLEL="heartcode-chat-sfw=1,heartcode-chat-nsfw=1")
    _pre(g, _chat(call_id="a"))

    with pytest.raises(HTTPException) as err:
        _pre(g, _chat(call_id="b"))
    assert err.value.status_code == 429
    assert err.value.headers["Retry-After"]

    # The other group has its own allowance.
    _pre(g, _chat(call_id="c", model="heartcode-chat-nsfw"))


def test_an_alias_cannot_take_a_second_slot(monkeypatch):
    g = _guard(monkeypatch)
    _pre(g, _chat(call_id="a"))
    with pytest.raises(HTTPException):
        _pre(g, _chat(call_id="b", model="heartcode-chat"))


def test_success_releases_a_plain_request(monkeypatch):
    g = _guard(monkeypatch)
    data = _pre(g, _chat(call_id="a"))
    asyncio.run(g.async_post_call_success_hook(data, PUBLIC, {"ok": True}))
    assert g.gate.in_flight("heartcode-chat-sfw") == 0


def test_failure_releases(monkeypatch):
    g = _guard(monkeypatch)
    data = _pre(g, _chat(call_id="a"))
    asyncio.run(g.async_post_call_failure_hook(data, RuntimeError("boom"), PUBLIC))
    assert g.gate.in_flight("heartcode-chat-sfw") == 0


def test_a_refused_request_releases_nothing(monkeypatch):
    """The failure hook also fires for the 429 itself; it must not free the
    slot the admitted request still holds."""
    g = _guard(monkeypatch)
    _pre(g, _chat(call_id="a"))
    refused = _chat(call_id="b")
    with pytest.raises(HTTPException):
        _pre(g, refused)
    asyncio.run(g.async_post_call_failure_hook(refused, RuntimeError("429"), PUBLIC))
    assert g.gate.in_flight("heartcode-chat-sfw") == 1


def test_a_stream_holds_its_slot_until_it_ends(monkeypatch):
    g = _guard(monkeypatch)
    data = _pre(g, _chat(call_id="a", stream=True))
    asyncio.run(g.async_post_call_success_hook(data, PUBLIC, None))
    assert g.gate.in_flight("heartcode-chat-sfw") == 1

    async def chunks():
        for i in range(3):
            yield i

    async def drain():
        return [c async for c in g.async_post_call_streaming_iterator_hook(PUBLIC, chunks(), data)]

    assert asyncio.run(drain()) == [0, 1, 2]
    assert g.gate.in_flight("heartcode-chat-sfw") == 0


def test_an_abandoned_stream_releases(monkeypatch):
    g = _guard(monkeypatch)
    data = _pre(g, _chat(call_id="a", stream=True))

    async def chunks():
        for i in range(10):
            yield i

    async def take_one_and_disconnect():
        stream = g.async_post_call_streaming_iterator_hook(PUBLIC, chunks(), data)
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(take_one_and_disconnect())
    assert g.gate.in_flight("heartcode-chat-sfw") == 0


def test_a_slot_nobody_released_expires():
    gate = guard.AdmissionGate({}, 1)
    gate.acquire("lost", "heartcode-chat-sfw", now=0.0)
    gate.acquire("next", "heartcode-chat-sfw", now=guard.STALE_AFTER_SECONDS + 1)
    assert gate.in_flight("heartcode-chat-sfw") == 1


def test_alias_table_matches_the_router_config():
    config = yaml.safe_load((LITELLM_DIR / "config.yaml").read_text())
    assert guard.MODEL_GROUP_ALIASES == config["router_settings"]["model_group_alias"]


def test_guard_is_registered_and_mounted():
    config = yaml.safe_load((LITELLM_DIR / "config.yaml").read_text())
    assert "public_api_guard.public_api_guard" in config["litellm_settings"]["callbacks"]
    compose = (LITELLM_DIR / "docker-compose.yml").read_text()
    assert "./public_api_guard.py:/app/public_api_guard.py:ro" in compose
