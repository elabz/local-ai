"""Live isolated LiteLLM routing contract; requires the disposable test stack.

    docker compose -f docker-compose.litellm-routing-test.yml up -d --wait
    LITELLM_GPU_TEST_URL=http://localhost:4410 pytest -q test_litellm_gpu_routing.py

The stack pins the same LiteLLM digest as litellm/docker-compose.yml, so what
passes here is what Prod's router does.
"""

import json
import os
import re
import time
from pathlib import Path

import httpx
import pytest
import yaml

BASE_URL = os.getenv("LITELLM_GPU_TEST_URL")
TEST_KEY = os.getenv("LITELLM_GPU_TEST_KEY", "test-gpu-routing-key")
# Host ports the fake backends publish (see docker-compose.litellm-routing-test.yml).
BUSY_STATS = os.getenv("LITELLM_GPU_TEST_BUSY_STATS", "http://localhost:4412/stats")
FLAKY_STATS = os.getenv("LITELLM_GPU_TEST_FLAKY_STATS", "http://localhost:4413/stats")
HEALTHY_STATS = os.getenv("LITELLM_GPU_TEST_HEALTHY_STATS", "http://localhost:4411/stats")
SPEECH_DEFAULTS = os.getenv("LITELLM_GPU_TEST_SPEECH_DEFAULTS", "http://localhost:4415")
STT = os.getenv("LITELLM_GPU_TEST_STT", "http://localhost:4416")
TTS = os.getenv("LITELLM_GPU_TEST_TTS", "http://localhost:4417")

pytestmark = pytest.mark.skipif(not BASE_URL, reason="isolated LiteLLM stack is not configured")

PROBE_CHAT = "/v1/chat/completions probe"
PROBE_STT = "/v1/audio/transcriptions probe"
PROBE_TTS = "/v1/audio/speech probe"
# HeartCode's whole added-wait budget for one speech operation
# (SPEECH_RETRY_DEADLINE_SECONDS); a LiteLLM-side retry must never outlast it.
CALLER_RETRY_BUDGET_SECONDS = 2.0


def request(path: str, **kwargs):
    headers = {"Authorization": f"Bearer {TEST_KEY}"}
    return httpx.request(kwargs.pop("method", "GET"), f"{BASE_URL}{path}", headers=headers, timeout=30, **kwargs)


def chat(model: str):
    return request(
        "/v1/chat/completions",
        method="POST",
        json={"model": model, "messages": [{"role": "user", "content": "routing-probe"}], "max_tokens": 4},
    )


def transcribe(model: str):
    headers = {"Authorization": f"Bearer {TEST_KEY}"}
    return httpx.post(
        f"{BASE_URL}/v1/audio/transcriptions",
        headers=headers,
        timeout=60,
        data={"model": model},
        files={"file": ("probe.wav", b"RIFF routing-probe", "audio/wav")},
    )


def speak(model: str):
    return request(
        "/v1/audio/speech", method="POST", json={"model": model, "input": "routing-probe", "voice": "af_heart"}
    )


def stats(url: str) -> dict:
    return httpx.get(url, timeout=5).json()["counts"]


def fail_next(backend: str, n: int) -> None:
    """Make the fake at `backend` answer its next n probe requests with a 500."""
    httpx.post(f"{backend}/fail", params={"n": n}, timeout=5).raise_for_status()


def cooldown_events() -> dict:
    """litellm_deployment_cooled_down_total samples keyed by api_base (0 when absent).

    Match the counter exactly: the exposition also carries a
    `..._cooled_down_created` timestamp gauge that must not be summed in."""
    text = request("/metrics/").text
    events = {}
    for line in text.splitlines():
        if not line.startswith("litellm_deployment_cooled_down_total{"):
            continue
        base = re.search(r'api_base="([^"]+)"', line)
        value = float(line.rsplit(" ", 1)[1])
        if base:
            events[base.group(1)] = events.get(base.group(1), 0.0) + value
    return events


def cooldowns_for(host: str) -> float:
    return sum(v for k, v in cooldown_events().items() if host in k)


# --- existing embedding contract ------------------------------------------------

def test_one_unavailable_replica_is_excluded_and_sibling_serves():
    health = request("/health", params={"model": "gpu-routing-one-down"})
    assert health.status_code == 200
    state = health.json()
    assert len(state["healthy_endpoints"]) == 1
    assert len(state["unhealthy_endpoints"]) == 1

    response = request(
        "/v1/embeddings",
        method="POST",
        json={"model": "gpu-routing-one-down", "input": "bounded integration probe"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["embedding"] == [0.25, 0.75]


def test_all_unavailable_returns_service_unavailable():
    health = request("/health", params={"model": "gpu-routing-all-down"})
    assert health.status_code == 200
    state = health.json()
    assert len(state["healthy_endpoints"]) == 0
    assert len(state["unhealthy_endpoints"]) == 2

    response = request(
        "/v1/embeddings",
        method="POST",
        json={"model": "gpu-routing-all-down", "input": "bounded integration probe"},
    )
    assert response.status_code == 503


# --- queue-busy-chat-backends -------------------------------------------------------

def test_router_policy_matches_production_base_config():
    """The disposable stack must exercise the router block Prod actually runs."""
    here = Path(__file__).resolve()
    test_router = yaml.safe_load(here.with_name("litellm_gpu_routing.yaml").read_text())["router_settings"]
    prod_router = yaml.safe_load((here.parents[3] / "litellm" / "config.base.yaml").read_text())["router_settings"]
    for key in ("allowed_fails", "cooldown_time", "num_retries", "routing_strategy", "allowed_fails_policy"):
        assert test_router[key] == prod_router[key], key
    # Without an explicit policy LiteLLM 1.81.9 ignores allowed_fails==3 (its
    # default) and cools a replica on its first 429 when a sibling exists.
    assert prod_router["allowed_fails_policy"]["RateLimitErrorAllowedFails"] >= 1000
    # Spec: cooldown needs >1 failure and lasts no longer than a generation.
    assert prod_router["allowed_fails"] >= 3
    assert prod_router["cooldown_time"] <= 30
    assert prod_router["num_retries"] >= 2


def test_busy_429_is_retried_on_sibling_and_does_not_cool_the_busy_replica():
    busy_before = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)
    cooled_before = cooldowns_for("gpu-test-busy")

    responses = [chat("chat-busy-with-sibling") for _ in range(6)]
    assert [r.status_code for r in responses] == [200] * 6
    assert all(r.json()["choices"][0]["message"]["content"] == "served-by-healthy" for r in responses)

    busy_after = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)
    # The busy replica was offered traffic and answered 429; the router moved on.
    assert busy_after > busy_before
    assert cooldowns_for("gpu-test-busy") == cooled_before


def test_single_busy_replica_surfaces_429_and_stays_routable():
    cooled_before = cooldowns_for("gpu-test-busy")

    first = chat("chat-busy-only")
    assert first.status_code == 429, first.text
    hits_after_first = stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0)

    # If the replica had been cooled the router would answer without contacting
    # it (no deployments available). It must still be tried.
    second = chat("chat-busy-only")
    assert second.status_code == 429, second.text
    assert stats(BUSY_STATS).get(f"{PROBE_CHAT} 429", 0) > hits_after_first
    assert cooldowns_for("gpu-test-busy") == cooled_before
    assert "BACKEND_BUSY" in second.text or "busy" in second.text.lower()


def test_single_transient_503_is_retried_elsewhere_and_replica_remains_routable():
    cooled_before = cooldowns_for("gpu-test-flaky")

    responses = [chat("chat-flaky-with-sibling") for _ in range(8)]
    assert [r.status_code for r in responses] == [200] * 8

    counts = stats(FLAKY_STATS)
    assert counts.get(f"{PROBE_CHAT} 503", 0) == 1
    # After its one 503 the flaky replica kept receiving traffic and served it.
    assert counts.get(f"{PROBE_CHAT} 200", 0) >= 1, counts
    assert cooldowns_for("gpu-test-flaky") == cooled_before


def test_cooldown_metric_is_exposed_for_alerting():
    """monitoring alerts key on litellm_deployment_cooled_down; make sure the
    pinned image still exports it (name drift would silently mute the alert)."""
    text = request("/metrics/").text
    assert "litellm_deployment_cooled_down" in text
    assert "litellm_proxy_total_requests_metric" in text


# --- serve-speech-cooldown-tuning ----------------------------------------------------

SPEECH_KEYS = {"cooldown_time": 0, "num_retries": 0}


def _deployments(config: dict, model_name: str) -> list[dict]:
    return [m["litellm_params"] for m in config["model_list"] if m["model_name"] == model_name]


def test_speech_params_match_production():
    """The tuned groups here carry exactly what heartcode-stt/-tts ship with."""
    here = Path(__file__).resolve()
    manifest = yaml.safe_load((here.parents[2] / "models.yaml").read_text())
    shipped = {m["api_name"]: m.get("params") or {} for m in manifest["models"]}
    test_config = yaml.safe_load(here.with_name("litellm_gpu_routing.yaml").read_text())
    for api_name, test_group in (("heartcode-stt", "speech-stt"), ("heartcode-tts", "speech-tts")):
        for key, value in SPEECH_KEYS.items():
            assert shipped[api_name].get(key) == value, (api_name, key)
        (deployment,) = _deployments(test_config, test_group)
        for key, value in SPEECH_KEYS.items():
            assert deployment.get(key) == value, (test_group, key)
    # The control group must stay on the router defaults, or it proves nothing.
    (control,) = _deployments(test_config, "speech-stt-defaults")
    assert not set(SPEECH_KEYS) & set(control)


def _assert_cooled_on_router_defaults(call, model: str, backend: str, probe: str):
    attempts = lambda: stats(f"{backend}/stats").get(f"{probe} 500", 0)  # noqa: E731
    fail_next(backend, 1000)
    try:
        before = attempts()
        statuses = [call(model).status_code for _ in range(4)]
        tried = attempts() - before
    finally:
        fail_next(backend, 0)
    # allowed_fails=3: the first request fails three times (two router
    # retries), the second fails a 4th time and cools the deployment, and every
    # later request is refused with 429 without reaching it.
    assert statuses[-1] == 429, statuses
    assert tried == 4, tried


def test_sole_speech_deployment_on_router_defaults_is_cooled():
    """Control: without the per-deployment keys, a sole deployment IS cooled and
    then refused without being tried -- the 2026-09-09 STT outage. If a LiteLLM
    bump makes this fail, the router changed underneath the speech settings:
    re-run the serve-speech-cooldown-tuning findings before trusting them."""
    _assert_cooled_on_router_defaults(transcribe, "speech-stt-defaults", SPEECH_DEFAULTS, PROBE_STT)


def test_only_speech_groups_override_the_router_policy():
    """Chat and every other generated deployment keep the router-wide cooldown
    and retry policy; only heartcode-stt/-tts opt out."""
    generated = yaml.safe_load((Path(__file__).resolve().parents[3] / "litellm" / "config.yaml").read_text())
    overriding = {
        m["model_name"] for m in generated["model_list"] if set(SPEECH_KEYS) & set(m["litellm_params"])
    }
    assert overriding == {"heartcode-stt", "heartcode-tts"}


def _assert_sole_deployment_fails_fast_and_stays_routable(call, model: str, backend: str, host: str, probe: str):
    cooled_before = cooldowns_for(host)
    failures = 5  # more than allowed_fails (3), so a count-based cooldown would trigger
    fail_next(backend, failures)
    try:
        for i in range(failures):
            before = stats(f"{backend}/stats").get(f"{probe} 500", 0)
            started = time.monotonic()
            response = call(model)
            elapsed = time.monotonic() - started
            assert response.status_code == 500, (i, response.status_code, response.text)
            # Exactly one attempt: LiteLLM does not retry, so it cannot outlast
            # the caller, whose own jittered retries are the only ones.
            assert stats(f"{backend}/stats").get(f"{probe} 500", 0) == before + 1, i
            assert elapsed < CALLER_RETRY_BUDGET_SECONDS, (i, elapsed)
    finally:
        fail_next(backend, 0)
    served = call(model)
    assert served.status_code == 200, served.text
    assert cooldowns_for(host) == cooled_before


def test_sole_stt_deployment_is_never_cooled_and_fails_fast():
    _assert_sole_deployment_fails_fast_and_stays_routable(transcribe, "speech-stt", STT, "gpu-test-stt", PROBE_STT)


def test_sole_tts_deployment_is_never_cooled_and_fails_fast():
    _assert_sole_deployment_fails_fast_and_stays_routable(speak, "speech-tts", TTS, "gpu-test-tts", PROBE_TTS)


# --- serve-prompt-cache-reuse: session affinity and streamed reuse figures ----

AFFINITY_STATS = os.getenv("LITELLM_GPU_TEST_AFFINITY_STATS", "http://localhost:4418")


def affinity_chat(session_id=None, where="header", stream=False):
    headers = {"Authorization": f"Bearer {TEST_KEY}"}
    body = {"model": "chat-affinity", "messages": [{"role": "user", "content": "routing-probe"}], "max_tokens": 4}
    if session_id and where == "header":
        headers["X-Session-Id"] = session_id
    elif session_id:
        body["metadata"] = {"session_id": session_id}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return httpx.post(f"{BASE_URL}/v1/chat/completions", headers=headers, json=body, timeout=30)


def served_by(response) -> str:
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


@pytest.mark.parametrize("where", ["header", "metadata"])
def test_a_session_keeps_its_replica_on_an_idle_pool(where):
    replicas = {served_by(affinity_chat(f"conv-{where}-1", where=where)) for _ in range(12)}
    assert len(replicas) == 1, replicas


def test_distinct_sessions_and_anonymous_requests_still_spread():
    sessions = {served_by(affinity_chat(f"conv-spread-{n}")) for n in range(30)}
    anonymous = {served_by(affinity_chat()) for _ in range(30)}
    assert len(sessions) == 3, sessions
    assert len(anonymous) == 3, anonymous


def test_streamed_usage_carries_cached_tokens_through_the_proxy():
    response = affinity_chat("conv-stream", stream=True)
    response.raise_for_status()
    usage = None
    for line in response.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[6:])
            usage = chunk.get("usage") or usage
    assert usage is not None, response.text
    assert (usage.get("prompt_tokens_details") or {}).get("cached_tokens") == 7, usage


def test_the_proxy_forwards_stream_options_to_the_backend():
    # Every session that hashes to replica 1 lands there; send a few distinct ones.
    for n in range(12):
        affinity_chat(f"conv-opts-{n}", stream=True).raise_for_status()
    last = httpx.get(f"{AFFINITY_STATS}/last-chat", timeout=5).json()
    assert last.get("stream") is True
    assert (last.get("stream_options") or {}).get("include_usage") is True, last
