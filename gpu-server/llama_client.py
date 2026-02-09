"""Client for communicating with llama.cpp server."""

import asyncio
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


class LlamaClient:
    """Async client for llama.cpp server API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8081):
        self.base_url = f"http://{host}:{port}"
        self.timeout = httpx.Timeout(settings.request_timeout, connect=10.0)

    async def health_check(self) -> dict:
        """Check if llama.cpp server is healthy."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self.base_url}/health")
            return response.json()

    async def get_model_info(self) -> dict:
        """Get loaded model information."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/props")
            return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def completion(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Generate completion (non-streaming)."""
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens or settings.default_max_tokens,
            "temperature": temperature or settings.default_temperature,
            "top_p": top_p or settings.default_top_p,
            "top_k": top_k or settings.default_top_k,
            "repeat_penalty": repeat_penalty or settings.default_repeat_penalty,
            "stream": False,
        }

        if stop:
            payload["stop"] = stop

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/completion",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def completion_stream(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate completion with streaming."""
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens or settings.default_max_tokens,
            "temperature": temperature or settings.default_temperature,
            "top_p": top_p or settings.default_top_p,
            "top_k": top_k or settings.default_top_k,
            "repeat_penalty": repeat_penalty or settings.default_repeat_penalty,
            "stream": True,
        }

        if stop:
            payload["stop"] = stop

        # Debug: Log the prompt for troubleshooting
        logger.info(f"Sending completion request with prompt length: {len(payload['prompt'])}")
        logger.debug(f"Prompt: {payload['prompt'][:500]}...")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/completion",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error(f"Completion request failed: {response.status_code} - {error_text.decode()}")
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        try:
                            import orjson
                            chunk = orjson.loads(data)
                            content = chunk.get("content", "")
                            if content:
                                yield content

                            # Check for stop condition
                            if chunk.get("stop", False):
                                break
                        except Exception as e:
                            logger.warning(f"Failed to parse chunk: {e}")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        OpenAI-compatible chat completion.
        Converts messages to llama.cpp prompt format.
        """
        # Convert chat messages to prompt
        prompt = self._messages_to_prompt(messages)

        if stream:
            # Return generator for streaming
            return self.completion_stream(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        else:
            result = await self.completion(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )

            # Convert to OpenAI format
            return {
                "id": f"chatcmpl-{settings.server_id}",
                "object": "chat.completion",
                "model": settings.model_path.split("/")[-1],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": result.get("content", ""),
                        },
                        "finish_reason": "stop" if result.get("stop", False) else "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": result.get("tokens_evaluated", 0),
                    "completion_tokens": result.get("tokens_predicted", 0),
                    "total_tokens": result.get("tokens_evaluated", 0) + result.get("tokens_predicted", 0),
                },
            }

    def _messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Convert chat messages to prompt format based on configured template.
        Dispatches to the appropriate template method.
        """
        template = settings.chat_template.lower()
        
        if template == "llama3":
            return self._llama3_template(messages)
        elif template == "chatml":
            return self._chatml_template(messages)
        else:
            logger.warning(f"Unknown chat template \"{template}\", defaulting to llama3")
            return self._llama3_template(messages)

    def _llama3_template(self, messages: List[Dict[str, str]]) -> str:
        """
        Llama 3 chat template format.
        Reference: https://llama.meta.com/docs/model-cards-and-prompt-formats/meta-llama-3/
        """
        prompt_parts = ["<|begin_of_text|>"]

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role == "system":
                prompt_parts.append(f"<|start_header_id|>system<|end_header_id|>\n\n{content}<|eot_id|>")
            elif role == "user":
                prompt_parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>")
            elif role == "assistant":
                prompt_parts.append(f"<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>")

        # Add assistant prefix for generation
        prompt_parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")

        return "".join(prompt_parts)

    def _chatml_template(self, messages: List[Dict[str, str]]) -> str:
        """
        ChatML format (used by many models like Mistral, etc.)
        Reference: https://github.com/openai/openai-python/blob/main/chatml.md
        """
        prompt_parts = []

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role == "system":
                prompt_parts.append(f"<|im_start|>system\\n{content}<|im_end|>")
            elif role == "user":
                prompt_parts.append(f"<|im_start|>user\\n{content}<|im_end|>")
            elif role == "assistant":
                prompt_parts.append(f"<|im_start|>assistant\\n{content}<|im_end|>")

        # Add assistant prefix for generation
        prompt_parts.append("<|im_start|>assistant\\n")

        return "\\n".join(prompt_parts)

    async def tokenize(self, text: str) -> Dict[str, Any]:
        """Tokenize text and return token count."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/tokenize",
                json={"content": text},
            )
            response.raise_for_status()
            return response.json()

    async def detokenize(self, tokens: List[int]) -> str:
        """Convert tokens back to text."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/detokenize",
                json={"tokens": tokens},
            )
            response.raise_for_status()
            return response.json().get("content", "")
