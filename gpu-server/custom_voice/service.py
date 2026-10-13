"""Production wiring for the private custom-voice control plane (uvicorn entrypoint).

    uvicorn custom_voice.service:app --host 0.0.0.0 --port 8080

Configuration (all secrets live in 0600 files under the private root, never env):
- CUSTOM_VOICE_PRIVATE_ROOT          default /private
- CUSTOM_VOICE_SERVICE_KEYS_FILE     {key_id: {"secret": str, "scopes": [str]}}
- CUSTOM_VOICE_CALLBACK_TARGETS_FILE {callback_id: {"url": str, "secret": str}}
- CUSTOM_VOICE_SAMPLE_ORIGINS        comma-separated origins intake may fetch from
- CUSTOM_VOICE_KOKORO_URL            default http://speech-tts:8880 (voice discovery)
- CUSTOM_VOICE_RATE_LIMIT            requests per key per minute, default 60
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .auth import ReplayStore, RequestAuthenticator, ServiceKey
from .callbacks import CallbackDispatcher, CallbackTarget
from .control_plane import create_app
from .intake_pull import httpx_fetch, normalize_origins, pull_intake
from .job_view import JobNotifier
from .jobs import JobStore
from .lifecycle import Lifecycle


class PrivateRoot:
    def __init__(self, root: Path):
        self.root = root
        self.intake = root / "custom-voice-intake"
        self.jobs_db = root / "custom-voice-jobs" / "jobs.sqlite3"
        self.control = root / "custom-voice-control"
        self.replay_db = self.control / "replay.sqlite3"
        self.map = self.control / "custom-voice-map.json"
        self.registry = root / "custom-voice-registry" / "registry.json"
        self.deletions = root / "custom-voice-registry" / "deletions"
        self.artifacts = root / "custom-voice-artifacts"
        self.previews = root / "custom-voice-previews"
        self.workspaces = root / "custom-voice-workspaces"
        self.results = root / "custom-voice-results"


def _private_json(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise RuntimeError("secret_file_permissions_too_open")
    return json.loads(path.read_text(encoding="utf-8"))


def load_service_keys(path: Path) -> dict[str, ServiceKey]:
    return {
        key_id: ServiceKey(value["secret"].encode(), frozenset(value["scopes"]))
        for key_id, value in _private_json(path).items()
    }


def load_callback_targets(path: Path) -> dict[str, CallbackTarget]:
    return {
        callback_id: CallbackTarget(value["url"], value["secret"].encode())
        for callback_id, value in _private_json(path).items()
    }


def _strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_strings(item) for item in value)) if value else set()
    return set()


def kokoro_discovery(base_url: str):
    def discover() -> set[str]:
        try:
            response = httpx.get(base_url.rstrip("/") + "/v1/audio/voices", timeout=10)
        except httpx.HTTPError:
            return set()
        if response.status_code != 200:
            return set()
        return _strings(response.json())

    return discover


def build_app(environ: dict[str, str] | None = None):
    env = os.environ if environ is None else environ
    paths = PrivateRoot(Path(env.get("CUSTOM_VOICE_PRIVATE_ROOT", "/private")))
    keys = load_service_keys(Path(env.get("CUSTOM_VOICE_SERVICE_KEYS_FILE", str(paths.control / "service-keys.json"))))
    targets = load_callback_targets(Path(env.get("CUSTOM_VOICE_CALLBACK_TARGETS_FILE", str(paths.control / "callback-targets.json"))))
    origins = normalize_origins(env.get("CUSTOM_VOICE_SAMPLE_ORIGINS", "").split(","))
    jobs = JobStore(paths.jobs_db)
    authenticator = RequestAuthenticator(keys, ReplayStore(paths.replay_db), rate_limit=int(env.get("CUSTOM_VOICE_RATE_LIMIT", "60")))
    dispatcher = CallbackDispatcher(targets, httpx.post) if targets else None
    lifecycle = Lifecycle(
        registry_path=paths.registry,
        map_path=paths.map,
        artifact_root=paths.artifacts,
        deletion_queue=paths.deletions,
        preview_root=paths.previews,
        discover=kokoro_discovery(env.get("CUSTOM_VOICE_KOKORO_URL", "http://speech-tts:8880")),
    )
    fetch = httpx_fetch()
    return create_app(
        jobs=jobs,
        authenticator=authenticator,
        preview_root=paths.previews,
        mutation_handlers={
            "stage": lifecycle.stage,
            "activate": lifecycle.activate,
            "rollback": lifecycle.rollback,
            "retire": lifecycle.retire,
            "delete": lifecycle.delete,
        },
        intake_puller=lambda request: pull_intake(request, intake_root=paths.intake, allowed_origins=origins, fetch=fetch),
        intake_root=paths.intake,
        notifier=JobNotifier(jobs, dispatcher),
        callback_ids=frozenset(targets),
        registry_reader=lifecycle.registry_view,
        deletion_reader=lifecycle.deletion,
    )


def __getattr__(name: str):
    # `uvicorn custom_voice.service:app` builds the app lazily, so importing
    # this module (tests, tooling) never opens the private root.
    if name == "app":
        return build_app()
    raise AttributeError(name)
