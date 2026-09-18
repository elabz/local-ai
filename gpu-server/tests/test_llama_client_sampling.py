import unittest
from unittest.mock import AsyncMock, patch

from llama_client import LlamaClient


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": []}


class _Client:
    def __init__(self, *args, **kwargs):
        self.post = AsyncMock(return_value=_Response())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class LlamaClientSamplingTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_preserves_explicit_zero_temperature(self):
        fake = _Client()
        with patch("llama_client.httpx.AsyncClient", return_value=fake):
            await LlamaClient().chat_completion(
                messages=[{"role": "user", "content": "test"}],
                temperature=0,
                top_p=0,
                top_k=0,
                repeat_penalty=0,
            )
        payload = fake.post.await_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["top_p"], 0)
        self.assertEqual(payload["top_k"], 0)
        self.assertEqual(payload["repeat_penalty"], 0)


if __name__ == "__main__":
    unittest.main()
