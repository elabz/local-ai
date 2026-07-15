import sys
import unittest
from pathlib import Path
from unittest.mock import patch


GPU_SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GPU_SERVER))

from llama_client import LlamaClient, _optional_sampling_params  # noqa: E402
from routes import ChatCompletionRequest, CompletionRequest  # noqa: E402


ADVANCED = {
    "min_p": 0.15,
    "dry_multiplier": 0.8,
    "dry_base": 1.75,
    "dry_allowed_length": 2,
    "dry_penalty_last_n": 4096,
    "xtc_threshold": 0.08,
    "xtc_probability": 0.5,
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {"content": "ok", "payload": self.payload}


class FakeAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, json):
        self.calls.append((url, json))
        return FakeResponse(json)


class SamplingPassthroughTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeAsyncClient.calls.clear()

    def test_request_models_accept_advanced_sampler_fields(self):
        completion = CompletionRequest(prompt="hello", **ADVANCED)
        chat = ChatCompletionRequest(
            messages=[{"role": "user", "content": "hello"}], **ADVANCED
        )

        for name, value in ADVANCED.items():
            self.assertEqual(getattr(completion, name), value)
            self.assertEqual(getattr(chat, name), value)

    def test_optional_sampler_values_preserve_zero_and_omit_none(self):
        self.assertEqual(
            _optional_sampling_params(min_p=0.0, xtc_probability=None),
            {"min_p": 0.0},
        )

    async def test_completion_forwards_advanced_sampler_fields(self):
        with patch("llama_client.httpx.AsyncClient", FakeAsyncClient):
            await LlamaClient().completion("hello", **ADVANCED)

        payload = FakeAsyncClient.calls[0][1]
        for name, value in ADVANCED.items():
            self.assertEqual(payload[name], value)

    async def test_chat_forwards_advanced_sampler_fields(self):
        with patch("llama_client.httpx.AsyncClient", FakeAsyncClient):
            await LlamaClient().chat_completion(
                [{"role": "user", "content": "hello"}], **ADVANCED
            )

        payload = FakeAsyncClient.calls[0][1]
        for name, value in ADVANCED.items():
            self.assertEqual(payload[name], value)


if __name__ == "__main__":
    unittest.main()
