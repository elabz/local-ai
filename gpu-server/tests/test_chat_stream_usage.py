"""Streamed chat passes llama-server's usage on (serve-prompt-cache-reuse §2).

llama-server's last streamed chunk carries `usage` with
`prompt_tokens_details.cached_tokens` and `timings`. The wrapper used to keep
only content deltas, so a streamed reply reached LiteLLM, and HeartCode,
without any prompt-cache figure.
"""
import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

GPU_SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GPU_SERVER))

from availability import BackendAvailability  # noqa: E402
from llama_client import LlamaClient  # noqa: E402
from routes import ChatCompletionRequest, _stream_chat_completion  # noqa: E402

USAGE = {"completion_tokens": 3, "prompt_tokens": 19, "total_tokens": 22,
         "prompt_tokens_details": {"cached_tokens": 14}}
TIMINGS = {"cache_n": 14, "prompt_n": 5, "prompt_ms": 87.5}
LLAMA_LINES = [
    'data: {"choices":[{"index":0,"delta":{"content":"Hel"}}]}',
    'data: {"choices":[{"index":0,"delta":{"content":"lo"}}]}',
    'data: {"choices":[{"finish_reason":"stop","index":0,"delta":{}}]}',
    "data: " + json.dumps({"choices": [], "usage": USAGE, "timings": TIMINGS}),
    "data: [DONE]",
]


class FakeStreamResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in LLAMA_LINES:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeAsyncClient:
    sent = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None):
        FakeAsyncClient.sent = json
        return FakeStreamResponse()


def test_client_asks_for_usage_and_records_it():
    sink = {}

    async def run():
        client = LlamaClient("127.0.0.1", 8081)
        return [t async for t in client.chat_completion_stream(
            messages=[{"role": "user", "content": "hi"}], usage_sink=sink)]

    with patch("llama_client.httpx.AsyncClient", FakeAsyncClient):
        tokens = asyncio.run(run())

    assert tokens == ["Hel", "lo"]
    assert FakeAsyncClient.sent["stream_options"] == {"include_usage": True}
    assert sink == {"usage": USAGE, "timings": TIMINGS}


class FakeLlama:
    async def chat_completion_stream(self, usage_sink=None, **kwargs):
        for token in ("Hel", "lo"):
            yield token
        usage_sink["usage"] = USAGE
        usage_sink["timings"] = TIMINGS


def _events(body):
    availability = BackendAvailability(max_in_flight=1)
    availability.probe_succeeded()
    assert availability.begin_request()
    state = types.SimpleNamespace(backend_availability=availability)
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=state))

    async def run():
        return [e["data"] async for e in _stream_chat_completion(request, FakeLlama(), [], body)]

    events = asyncio.run(run())
    assert availability.snapshot().in_flight == 0  # the slot is released
    return events


def test_usage_chunk_when_the_client_asks():
    body = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], stream=True,
                                 stream_options={"include_usage": True})
    events = _events(body)
    assert events[-1] == "[DONE]"
    usage_chunk = json.loads(events[-2])
    assert usage_chunk["choices"] == []
    assert usage_chunk["usage"]["prompt_tokens_details"]["cached_tokens"] == 14
    assert usage_chunk["timings"] == TIMINGS
    assert json.loads(events[-3])["choices"][0]["finish_reason"] == "stop"


def test_no_usage_chunk_unless_asked():
    body = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], stream=True)
    events = _events(body)
    assert events[-1] == "[DONE]"
    assert all("usage" not in json.loads(e) for e in events[:-1])
