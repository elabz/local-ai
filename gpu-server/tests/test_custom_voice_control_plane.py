import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.auth import ReplayStore, RequestAuthenticator, ServiceKey
from custom_voice.control_plane import create_app
from custom_voice.jobs import JobStore


def client(tmp_path: Path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    keys = {
        "admin-key": ServiceKey(b"secret-admin", frozenset({"custom_voice.build", "custom_voice.read", "custom_voice.preview.read", "custom_voice.activate", "custom_voice.delete"})),
        "speech-key": ServiceKey(b"secret-speech", frozenset({"speech.inference"})),
    }
    auth = RequestAuthenticator(keys, ReplayStore(tmp_path / "replay.sqlite3"), rate_limit=10)
    app = create_app(jobs=jobs, authenticator=auth, preview_root=tmp_path / "previews", mutation_handlers={"activate": lambda value: {**value, "state": "active"}})
    return TestClient(app), auth, jobs


def signed(auth, key_id: str, secret: bytes, method: str, path: str, body: bytes, nonce: str):
    timestamp = str(int(time.time()))
    return {
        "X-Custom-Voice-Key-Id": key_id,
        "X-Custom-Voice-Timestamp": timestamp,
        "X-Custom-Voice-Nonce": nonce,
        "X-Custom-Voice-Signature": auth.signature(secret, timestamp, nonce, method, path, body),
    }


def build_payload():
    return {
        "schema_version": "custom-voice-build-request.v1",
        "intake_id": "bench-speaker-001-v1",
        "manifest_sha256": "a" * 64,
        "stable_voice_id": "custom-bench-speaker-001",
        "version": "v1",
        "builder_profile": "kvoicewalk-multireference.v1",
        "callback": None,
    }


def test_signed_build_submission_and_authoritative_polling(tmp_path: Path) -> None:
    api, auth, _jobs = client(tmp_path)
    body = json.dumps(build_payload(), separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-builds"
    headers = signed(auth, "admin-key", b"secret-admin", "POST", path, body, "nonce-build-00001") | {"Content-Type": "application/json", "Idempotency-Key": "request-0001"}
    response = api.post(path, content=body, headers=headers)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    get_path = f"/internal/v1/custom-voice-builds/{job_id}"
    response = api.get(get_path, headers=signed(auth, "admin-key", b"secret-admin", "GET", get_path, b"", "nonce-read-000001"))
    assert response.status_code == 200
    assert response.json()["manifest_sha256"] == "a" * 64


def test_general_speech_key_cannot_create_job(tmp_path: Path) -> None:
    api, auth, jobs = client(tmp_path)
    body = json.dumps(build_payload(), separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-builds"
    headers = signed(auth, "speech-key", b"secret-speech", "POST", path, body, "nonce-speech-0001") | {"Content-Type": "application/json", "Idempotency-Key": "request-0001"}
    response = api.post(path, content=body, headers=headers)
    assert response.status_code == 403
    assert jobs.claim_next() is None


def test_replayed_request_is_rejected(tmp_path: Path) -> None:
    api, auth, _jobs = client(tmp_path)
    body = json.dumps(build_payload(), separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-builds"
    headers = signed(auth, "admin-key", b"secret-admin", "POST", path, body, "nonce-replay-0001") | {"Content-Type": "application/json", "Idempotency-Key": "request-0001"}
    assert api.post(path, content=body, headers=headers).status_code == 202
    response = api.post(path, content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "request_replayed"


def test_activation_requires_distinct_scope(tmp_path: Path) -> None:
    api, auth, _jobs = client(tmp_path)
    payload = {"stable_voice_id": "custom-demo", "version": "v1", "artifact_sha256": "a" * 64}
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-registry/activate"
    speech = signed(auth, "speech-key", b"secret-speech", "POST", path, body, "nonce-activate-01") | {"Content-Type": "application/json"}
    assert api.post(path, content=body, headers=speech).status_code == 403
    admin = signed(auth, "admin-key", b"secret-admin", "POST", path, body, "nonce-activate-02") | {"Content-Type": "application/json"}
    assert api.post(path, content=body, headers=admin).json()["state"] == "active"


def test_unknown_forward_contract_version_fails_closed(tmp_path: Path) -> None:
    api, auth, _jobs = client(tmp_path)
    payload = build_payload() | {"schema_version": "custom-voice-build-request.v2"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-builds"
    headers = signed(auth, "admin-key", b"secret-admin", "POST", path, body, "nonce-version-0001") | {"Content-Type": "application/json", "Idempotency-Key": "request-0001"}
    assert api.post(path, content=body, headers=headers).status_code == 422


def test_validation_error_never_echoes_protected_input(tmp_path: Path) -> None:
    api, auth, _jobs = client(tmp_path)
    payload = build_payload() | {"transcript": "protected words must not echo"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = "/internal/v1/custom-voice-builds"
    headers = signed(auth, "admin-key", b"secret-admin", "POST", path, body, "nonce-content-0001") | {"Content-Type": "application/json", "Idempotency-Key": "request-0001"}
    response = api.post(path, content=body, headers=headers)
    assert response.status_code == 422
    assert response.json() == {"type": "about:blank", "code": "request_invalid", "status": 422}
    assert "protected words" not in response.text
