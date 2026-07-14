"""Allowlist HeartCode correlation headers for LiteLLM speech provider calls."""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

import litellm
from litellm.integrations.custom_logger import CustomLogger
from litellm.llms.openai.transcriptions.handler import OpenAIAudioTranscription
from litellm.llms.openai.openai import OpenAIChatCompletion

SPEECH_MODELS = frozenset({"heartcode-stt", "heartcode-tts"})
ALLOWED_HEADERS = {
    "x-speech-request-id": "X-Speech-Request-ID",
    "x-call-id": "X-Call-ID",
    "x-turn-id": "X-Turn-ID",
}
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TTS_CORRELATION_HEADERS: ContextVar[dict[str, str]] = ContextVar(
    "tts_correlation_headers", default={}
)


def allowlisted_correlation_headers(data: dict[str, Any]) -> dict[str, str]:
    """Return only valid correlation headers for configured speech models."""
    request = data.get("proxy_server_request") or {}
    request_body = request.get("body") or {}
    requested_model = request_body.get("model")
    if data.get("model") not in SPEECH_MODELS and requested_model not in SPEECH_MODELS:
        return {}
    incoming = request.get("headers") or {}
    result: dict[str, str] = {}
    for name, value in incoming.items():
        canonical = ALLOWED_HEADERS.get(str(name).lower())
        text = str(value)
        if canonical and SAFE_VALUE.fullmatch(text):
            result[canonical] = text
    return result


class SpeechCorrelationCallback(CustomLogger):
    @staticmethod
    def _add_headers(data: dict[str, Any]) -> dict[str, Any]:
        forwarded = allowlisted_correlation_headers(data)
        if forwarded:
            data["extra_headers"] = {
                **(data.get("extra_headers") or {}),
                **forwarded,
            }
        return data

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return self._add_headers(data)

    async def async_pre_request_hook(self, model, messages, kwargs):
        # Audio endpoints in current LiteLLM releases bypass async_pre_call_hook
        # but retain proxy_server_request in provider kwargs.
        return self._add_headers({"model": model, **kwargs})


speech_correlation_callback = SpeechCorrelationCallback()


def _install_audio_adapter_shim() -> None:
    """Bridge current LiteLLM audio routes, which bypass callback pre-call hooks."""
    if getattr(litellm, "_heartcode_speech_correlation_installed", False):
        return
    original_router_atranscription = litellm.Router._atranscription
    original_router_aspeech = litellm.Router.aspeech
    original_openai_transcription = OpenAIAudioTranscription.audio_transcriptions
    original_openai_speech = OpenAIChatCompletion.audio_speech

    async def correlated_router_atranscription(router, file, model, **kwargs):
        kwargs = SpeechCorrelationCallback._add_headers({"model": model, **kwargs})
        kwargs.pop("model", None)
        return await original_router_atranscription(
            router, file=file, model=model, **kwargs
        )

    async def correlated_router_aspeech(router, model, input, voice, **kwargs):
        kwargs = SpeechCorrelationCallback._add_headers({"model": model, **kwargs})
        kwargs.pop("model", None)
        token = TTS_CORRELATION_HEADERS.set(kwargs.get("extra_headers") or {})
        try:
            return await original_router_aspeech(
                router, model=model, input=input, voice=voice, **kwargs
            )
        finally:
            TTS_CORRELATION_HEADERS.reset(token)

    def correlated_openai_transcription(handler, *args, **kwargs):
        # Current LiteLLM transcription parameter normalization drops
        # extra_headers before building the OpenAI SDK request. Restore only the
        # already-sanitized values carried in litellm_params.
        params = kwargs.get("litellm_params") or {}
        headers = allowlisted_correlation_headers(
            {
                "model": kwargs.get("model"),
                "proxy_server_request": params.get("proxy_server_request"),
            }
        )
        if headers:
            kwargs["optional_params"] = {
                **(kwargs.get("optional_params") or {}),
                "extra_headers": headers,
            }
        return original_openai_transcription(handler, *args, **kwargs)

    def correlated_openai_speech(handler, *args, **kwargs):
        headers = TTS_CORRELATION_HEADERS.get()
        if headers:
            kwargs["optional_params"] = {
                **(kwargs.get("optional_params") or {}),
                "extra_headers": headers,
            }
        return original_openai_speech(handler, *args, **kwargs)

    litellm.Router._atranscription = correlated_router_atranscription
    litellm.Router.aspeech = correlated_router_aspeech
    OpenAIAudioTranscription.audio_transcriptions = correlated_openai_transcription
    OpenAIChatCompletion.audio_speech = correlated_openai_speech
    litellm._heartcode_speech_correlation_installed = True


_install_audio_adapter_shim()
