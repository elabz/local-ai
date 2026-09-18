import asyncio
from unittest.mock import AsyncMock, Mock, patch

from llama_client import LlamaClient
from routes import Message


def test_tool_message_preserves_openai_fields():
    message = Message(
        role="assistant",
        content=None,
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
    )
    assert message.as_openai_dict() == {
        "role": "assistant",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
    }


def test_chat_client_forwards_schema_and_tool_fields():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": []}
    client_context = AsyncMock()
    client_context.__aenter__.return_value.post.return_value = response

    with patch("llama_client.httpx.AsyncClient", return_value=client_context):
        client = LlamaClient("http://127.0.0.1:8081")
        asyncio.run(
            client.chat_completion(
                messages=[{"role": "user", "content": "probe"}],
                response_format={"type": "json_object"},
                tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
                tool_choice="auto",
                parallel_tool_calls=False,
            )
        )

    payload = client_context.__aenter__.return_value.post.call_args.kwargs["json"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is False
