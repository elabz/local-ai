"""The control plane's actual responses validate against the published contract.

Drives the real app (real intake pull, lifecycle, job store, runner) and checks
every body against docs/contracts/custom-voice-control-plane-v1.yaml, so the
implementation cannot drift from the document HeartCode vendors.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.auth import ReplayStore, RequestAuthenticator, ServiceKey
from custom_voice.control_plane import create_app
from custom_voice.intake import IntakeProfile
from custom_voice.intake_pull import normalize_origins, pull_intake
from custom_voice.job_view import JobNotifier
from custom_voice.jobs import JobStore
from custom_voice.lifecycle import Lifecycle
from custom_voice.runner import Runner, RunnerConfig
from test_custom_voice_intake_pull import AUDIO, FakeOrigin
from test_custom_voice_intake_pull import request as intake_request
from test_custom_voice_lifecycle import seal
from test_custom_voice_runner import FakeScripts

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs" / "contracts" / "custom-voice-control-plane-v1.yaml").read_text())
PROFILE = IntakeProfile(adaptation_count=2, heldout_count=1, min_duration_seconds=0.5, max_duration_seconds=2.0)
SCOPES = frozenset({"custom_voice.build", "custom_voice.read", "custom_voice.preview.read", "custom_voice.activate", "custom_voice.delete"})


def validate(name: str, body: object) -> None:
    schema = {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]}
    errors = sorted(Draft202012Validator(schema).iter_errors(body), key=str)
    assert not errors, f"{name}: {[error.message for error in errors]}"


class Harness:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "private"
        self.jobs = JobStore(self.root / "custom-voice-jobs" / "jobs.sqlite3")
        self.auth = RequestAuthenticator({"heartcode": ServiceKey(b"secret", SCOPES)}, ReplayStore(tmp_path / "replay.sqlite3"), rate_limit=1000)
        self.lifecycle = Lifecycle(
            registry_path=self.root / "custom-voice-registry" / "registry.json",
            map_path=self.root / "custom-voice-control" / "custom-voice-map.json",
            artifact_root=self.root / "custom-voice-artifacts",
            deletion_queue=self.root / "custom-voice-registry" / "deletions",
            preview_root=self.root / "custom-voice-previews",
            discover=lambda: {"cv_custom_test_voice"},
        )
        intake_root = self.root / "custom-voice-intake"
        self.app = TestClient(create_app(
            jobs=self.jobs,
            authenticator=self.auth,
            preview_root=self.root / "custom-voice-previews",
            mutation_handlers={"stage": self.lifecycle.stage, "activate": self.lifecycle.activate, "rollback": self.lifecycle.rollback, "retire": self.lifecycle.retire, "delete": self.lifecycle.delete},
            intake_puller=lambda body: pull_intake(body, intake_root=intake_root, allowed_origins=normalize_origins(["http://heartcode.test:8000"]), fetch=FakeOrigin(), profile=PROFILE),
            intake_root=intake_root,
            notifier=JobNotifier(self.jobs, None),
            callback_ids=frozenset({"heartcode-dev"}),
            registry_reader=self.lifecycle.registry_view,
            deletion_reader=self.lifecycle.deletion,
        ))
        self.nonce = 0

    def call(self, method: str, path: str, body: dict | None = None, **headers: str):
        self.nonce += 1
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        timestamp, nonce = str(int(time.time())), f"nonce-conformance-{self.nonce:06d}"
        signed = {
            "X-Custom-Voice-Key-Id": "heartcode",
            "X-Custom-Voice-Timestamp": timestamp,
            "X-Custom-Voice-Nonce": nonce,
            "X-Custom-Voice-Signature": self.auth.signature(b"secret", timestamp, nonce, method, path.split("?")[0], raw),
            "Content-Type": "application/json",
            **headers,
        }
        return self.app.request(method, path, content=raw or None, headers=signed)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_intake_build_and_job_views_conform(harness: Harness) -> None:
    body = intake_request()
    production = json.loads(json.dumps(body))
    template = production["samples"][0]
    production["samples"] = [
        template | {"sample_id": f"sample-{index:03d}", "role": "adaptation" if index < 6 else "heldout"}
        for index in range(10)
    ]
    validate("IntakeRequest", production)  # the schema fixes the production profile's 6 + 4
    response = harness.call("POST", "/internal/v1/custom-voice-intakes", body, **{"Idempotency-Key": "intake-0000001"})
    assert response.status_code == 201, response.text
    validate("Intake", response.json())

    build = {
        "schema_version": "custom-voice-build-request.v1",
        "intake_id": body["intake_id"],
        "manifest_sha256": response.json()["manifest_sha256"],
        "stable_voice_id": body["stable_voice_id"],
        "version": body["version"],
        "builder_profile": "kvoicewalk-multireference.v1",
        "callback": {"callback_id": "heartcode-dev"},
    }
    validate("CreateBuildRequest", build)
    created = harness.call("POST", "/internal/v1/custom-voice-builds", build, **{"Idempotency-Key": "build-00000001"})
    assert created.status_code == 202, created.text
    validate("BuildJob", created.json())
    job_id = created.json()["job_id"]

    runner = Runner(harness.jobs, RunnerConfig(private_root=harness.root, worker_image="w", worker_image_digest="e" * 64, compat_image="c", runtime_image="k"), JobNotifier(harness.jobs, None), run=FakeScripts(harness.root), prepare=lambda **_kwargs: {})
    assert runner.run_once()
    read = harness.call("GET", f"/internal/v1/custom-voice-builds/{job_id}")
    assert read.status_code == 200
    assert read.json()["state"] == "succeeded"
    validate("BuildJob", read.json())
    validate("BuildResult", read.json()["result"])


def test_build_for_an_unknown_intake_or_callback_is_refused(harness: Harness) -> None:
    build = {
        "schema_version": "custom-voice-build-request.v1",
        "intake_id": "hc-missing",
        "manifest_sha256": "a" * 64,
        "stable_voice_id": "custom-test-voice",
        "version": "v1",
        "builder_profile": "kvoicewalk-multireference.v1",
        "callback": None,
    }
    missing = harness.call("POST", "/internal/v1/custom-voice-builds", build, **{"Idempotency-Key": "build-00000002"})
    assert missing.status_code == 404
    validate("SafeError", missing.json())
    unknown = harness.call("POST", "/internal/v1/custom-voice-builds", build | {"callback": {"callback_id": "someone-else"}}, **{"Idempotency-Key": "build-00000003"})
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "callback_target_unknown"


def test_registry_lifecycle_responses_conform(harness: Harness) -> None:
    v1 = seal(harness.root.parent, "v1", b"one")
    # seal() writes under <tmp>/artifacts; move it under the private root.
    (harness.root / "custom-voice-artifacts").mkdir(parents=True, exist_ok=True)
    (harness.root.parent / "artifacts" / "custom-test-voice").rename(harness.root / "custom-voice-artifacts" / "custom-test-voice")
    validate("ArtifactMutation", v1["mutation"])
    validate("ActivationRequest", v1["activation"])
    for path, body, schema in (
        ("/internal/v1/custom-voice-registry/stage", v1["mutation"], "RegistryVersion"),
        ("/internal/v1/custom-voice-registry/activate", v1["activation"], "RegistryVersion"),
    ):
        response = harness.call("POST", path, body)
        assert response.status_code == 200, response.text
        validate(schema, response.json())
    view = harness.call("GET", "/internal/v1/custom-voice-registry")
    validate("RegistryView", view.json())
    assert view.json()["voices"][0]["active_version"] == "v1"
    retired = harness.call("POST", "/internal/v1/custom-voice-registry/retire", v1["mutation"])
    validate("RegistryVersion", retired.json())
    deleted = harness.call("POST", "/internal/v1/custom-voice-deletions", v1["mutation"])
    assert deleted.status_code == 202, deleted.text
    validate("DeletionRequest", deleted.json())
    read = harness.call("GET", f"/internal/v1/custom-voice-deletions/{deleted.json()['request_id']}")
    validate("DeletionRequest", read.json())
    assert read.json()["state"] == "verified_deleted"


def test_activation_without_the_attestation_document_is_a_contract_422(harness: Harness) -> None:
    body = {"stable_voice_id": "custom-test-voice", "version": "v1", "artifact_sha256": "a" * 64, "sbom_sha256": "b" * 64, "admin_attestation_id": "hc-attest-v1"}
    response = harness.call("POST", "/internal/v1/custom-voice-registry/activate", body)
    assert response.status_code == 422
    validate("SafeError", response.json())


def test_digest_mismatch_is_a_content_free_safe_error(harness: Harness) -> None:
    body = intake_request()
    body["samples"][0]["audio_sha256"] = hashlib.sha256(AUDIO + b"!").hexdigest()
    response = harness.call("POST", "/internal/v1/custom-voice-intakes", body, **{"Idempotency-Key": "intake-0000002"})
    assert response.status_code == 422
    validate("SafeError", response.json())
    assert response.json()["code"] == "audio_digest_mismatch"
