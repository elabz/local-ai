"""The session-affinity callback (serve-prompt-cache-reuse, litellm/session_affinity.py).

It must hand the request's session id to the least-busy tie-break and never
change which deployments are eligible.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

LITELLM = Path(__file__).resolve().parents[2] / "litellm"


@pytest.fixture
def affinity(monkeypatch):
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    spec = importlib.util.spec_from_file_location("session_affinity_under_test", LITELLM / "session_affinity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _filter(module, request_kwargs):
    healthy = [{"model_info": {"id": "heartcode-gpu1"}}, {"model_info": {"id": "heartcode-gpu2"}}]

    async def run():
        returned = await module.session_affinity.async_filter_deployments(
            model="heartcode-chat-sfw", healthy_deployments=healthy, request_kwargs=request_kwargs
        )
        return returned, module.session_affinity_id.get()

    returned, seen = asyncio.run(run())
    assert returned is healthy  # never filters
    return seen


def test_header_sets_the_session(affinity):
    kwargs = {"metadata": {"headers": {"X-Session-Id": " 3f2a-conv "}}}
    assert _filter(affinity, kwargs) == "3f2a-conv"


def test_body_metadata_sets_the_session(affinity):
    assert _filter(affinity, {"metadata": {"session_id": "conv-9"}}) == "conv-9"
    assert _filter(affinity, {"litellm_metadata": {"session_id": "conv-9"}}) == "conv-9"


def test_header_wins_over_body(affinity):
    kwargs = {"metadata": {"headers": {"x-session-id": "from-header"}, "session_id": "from-body"}}
    assert _filter(affinity, kwargs) == "from-header"


@pytest.mark.parametrize(
    "kwargs",
    [None, {}, {"metadata": None}, {"metadata": {"headers": {"x-session-id": ""}}},
     {"metadata": {"session_id": 42}}, {"metadata": {"session_id": "x" * 129}}],
)
def test_no_usable_id_means_no_affinity(affinity, kwargs):
    assert _filter(affinity, kwargs) is None


def test_a_later_request_without_an_id_clears_it(affinity):
    async def run():
        healthy = [{"model_info": {"id": "a"}}]
        await affinity.session_affinity.async_filter_deployments(
            "m", healthy, request_kwargs={"metadata": {"session_id": "conv-1"}}
        )
        await affinity.session_affinity.async_filter_deployments("m", healthy, request_kwargs={})
        return affinity.session_affinity_id.get()

    assert asyncio.run(run()) is None


def test_the_proxy_loads_it():
    base = yaml.safe_load((LITELLM / "config.base.yaml").read_text())
    assert "session_affinity.session_affinity" in base["litellm_settings"]["callbacks"]
