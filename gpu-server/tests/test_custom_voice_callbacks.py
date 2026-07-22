import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.callbacks import CallbackDispatcher, CallbackError, CallbackTarget


class Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


def event():
    return {"schema_version": "custom-voice-callback.v1", "callback_id": "heartcode-prod", "event_id": 7, "job_id": "cvj_" + "a" * 32, "state": "succeeded", "occurred_at": "2026-07-17T21:00:00Z", "reason": "build_succeeded"}


def test_callback_retries_and_signs_content_safe_event() -> None:
    calls = []
    statuses = iter((503, 200))
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(next(statuses))
    dispatcher = CallbackDispatcher({"heartcode-prod": CallbackTarget("https://heartcode.internal/callbacks/custom-voice", b"secret")}, post, sleep=lambda _: None)
    result = dispatcher.deliver("heartcode-prod", event())
    assert result == {"outcome": "delivered", "attempts": 2, "status": 200}
    assert calls[0][0] == "https://heartcode.internal/callbacks/custom-voice"
    assert calls[0][1]["follow_redirects"] is False
    assert len(calls[0][1]["headers"]["X-Custom-Voice-Signature"]) == 64
    assert json.loads(calls[0][1]["content"])["state"] == "succeeded"


def test_unknown_callback_id_never_accepts_client_url() -> None:
    dispatcher = CallbackDispatcher({}, lambda *_args, **_kwargs: Response(200), sleep=lambda _: None)
    with pytest.raises(CallbackError, match="callback_target_unknown"):
        dispatcher.deliver("https://attacker.invalid", event())


def test_permanent_client_error_is_not_retried() -> None:
    calls = []
    dispatcher = CallbackDispatcher({"heartcode-prod": CallbackTarget("https://heartcode.internal/callback", b"secret")}, lambda *args, **kwargs: calls.append(1) or Response(400), sleep=lambda _: None)
    result = dispatcher.deliver("heartcode-prod", event())
    assert result == {"outcome": "failed", "attempts": 1, "status": 400}
    assert len(calls) == 1


def test_event_rejects_unapproved_content_field() -> None:
    unsafe = event() | {"transcript": "protected words"}
    dispatcher = CallbackDispatcher({"heartcode-prod": CallbackTarget("https://heartcode.internal/callback", b"secret")}, lambda *_args, **_kwargs: Response(200))
    with pytest.raises(CallbackError, match="callback_event_invalid"):
        dispatcher.deliver("heartcode-prod", unsafe)
