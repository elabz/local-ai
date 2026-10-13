"""Private FastAPI boundary for custom-voice build and lifecycle operations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, RequestAuthenticator
from .intake_pull import IntakeConflict, IntakePullError
from .job_view import JobNotifier, build_job_view
from .jobs import JobError, JobStore
from .lifecycle import LifecycleError
from .preview import PreviewError, read_protected_preview

VOICE_ID_PATTERN = r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
VERSION_PATTERN = r"^v[1-9][0-9]{0,8}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class CreateBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^custom-voice-build-request\.v1$")
    intake_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}[A-Za-z0-9]$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_voice_id: str = Field(pattern=r"^custom-[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    version: str = Field(pattern=r"^v[1-9][0-9]{0,8}$")
    builder_profile: str = Field(pattern=r"^kvoicewalk-multireference\.v1$")
    callback: dict | None = None


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stable_voice_id: str = Field(pattern=VOICE_ID_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)


class Activation(Mutation):
    sbom_sha256: str = Field(pattern=SHA256_PATTERN)
    admin_attestation_id: str = Field(pattern=r"^[A-Za-z0-9._-]{8,128}$")
    admin_attestation: dict


class IntakeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str
    role: str
    fetch_url: str = Field(max_length=2048)
    audio_sha256: str = Field(pattern=SHA256_PATTERN)
    transcript: str = Field(min_length=1, max_length=16384)
    sample_rate_hz: int
    channels: int
    encoding: str


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^custom-voice-intake-request\.v1$")
    intake_id: str
    stable_voice_id: str = Field(pattern=VOICE_ID_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    language: str
    authorization_id: str
    builder_profile: str
    samples: list[IntakeSample] = Field(min_length=1, max_length=64)


def safe_error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"type": "about:blank", "code": code, "status": status}, status_code=status, media_type="application/problem+json")


def create_app(
    *,
    jobs: JobStore,
    authenticator: RequestAuthenticator,
    preview_root: Path,
    mutation_handlers: dict[str, Callable[[dict], dict]] | None = None,
    intake_puller: Callable[[dict], dict] | None = None,
    intake_root: Path | None = None,
    notifier: JobNotifier | None = None,
    callback_ids: frozenset[str] | None = None,
    registry_reader: Callable[[], dict] | None = None,
    deletion_reader: Callable[[str], dict] | None = None,
) -> FastAPI:
    app = FastAPI(title="Private Custom Voice Control Plane", docs_url=None, redoc_url=None, openapi_url=None)
    handlers = mutation_handlers or {}

    def notify(job_id: str) -> None:
        if notifier is not None:
            notifier.notify(job_id)

    @app.exception_handler(AuthError)
    async def auth_error(_request: Request, error: AuthError):
        status = 429 if str(error) == "rate_limit_exceeded" else 403 if str(error) == "scope_forbidden" else 401
        return safe_error(str(error), status)

    @app.exception_handler(JobError)
    async def job_error(_request: Request, error: JobError):
        status = 404 if str(error) == "job_missing" else 409 if str(error) == "idempotency_conflict" else 400
        return safe_error(str(error), status)

    @app.exception_handler(PreviewError)
    async def preview_error(_request: Request, error: PreviewError):
        return safe_error(str(error), 403 if str(error) == "preview_forbidden" else 404)

    @app.exception_handler(IntakeConflict)
    async def intake_conflict(_request: Request, error: IntakeConflict):
        return safe_error(str(error), 409)

    @app.exception_handler(IntakePullError)
    async def intake_error(_request: Request, error: IntakePullError):
        # A failed fetch is worth retrying with freshly signed URLs.
        return safe_error(str(error), 502 if str(error) == "intake_fetch_failed" else 422)

    @app.exception_handler(LifecycleError)
    async def lifecycle_error(_request: Request, error: LifecycleError):
        return safe_error(str(error), 404 if str(error) in {"deletion_missing", "registry_version_missing", "artifact_missing"} else 409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return safe_error("request_invalid", 422)

    def require(scope: str):
        async def dependency(request: Request) -> str:
            body = await request.body()
            return authenticator.authenticate(headers=request.headers, method=request.method, path=request.url.path, body=body, required_scope=scope)
        return dependency

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/internal/v1/custom-voice-intakes", status_code=201)
    async def create_intake(payload: IntakeRequest, idempotency_key: str = Header(alias="Idempotency-Key"), _caller: str = Depends(require("custom_voice.build"))):
        if intake_puller is None:
            return safe_error("operation_unavailable", 503)
        return intake_puller(payload.model_dump())

    @app.post("/internal/v1/custom-voice-builds", status_code=202)
    async def create_build(payload: CreateBuild, idempotency_key: str = Header(alias="Idempotency-Key"), caller: str = Depends(require("custom_voice.build"))):
        callback_id = payload.callback.get("callback_id") if payload.callback else None
        if callback_id is not None and callback_ids is not None and callback_id not in callback_ids:
            return safe_error("callback_target_unknown", 422)
        if intake_root is not None:
            # Fail at submission, not hours later in the runner.
            try:
                manifest = (intake_root / payload.intake_id / "manifest.json").read_bytes()
            except (OSError, ValueError):
                return safe_error("intake_missing", 404)
            if hashlib.sha256(manifest).hexdigest() != payload.manifest_sha256:
                return safe_error("intake_manifest_mismatch", 409)
        job, created = jobs.create_job(caller_id=caller, idempotency_key=idempotency_key, intake_id=payload.intake_id, manifest_sha256=payload.manifest_sha256, builder_profile=payload.builder_profile, callback_id=callback_id)
        if created:
            notify(str(job["job_id"]))
        return build_job_view(job)

    @app.get("/internal/v1/custom-voice-builds/{job_id}")
    async def get_build(job_id: str, _caller: str = Depends(require("custom_voice.read"))):
        return build_job_view(jobs.get_job(job_id), jobs.events(job_id))

    @app.post("/internal/v1/custom-voice-builds/{job_id}/cancel", status_code=202)
    async def cancel_build(job_id: str, _caller: str = Depends(require("custom_voice.build"))):
        job = jobs.transition(job_id, "cancelling", "cancellation_requested")
        notify(job_id)
        return build_job_view(job)

    @app.get("/internal/v1/custom-voice-previews/{preview_id}")
    async def preview(preview_id: str, expected_sha256: str, _caller: str = Depends(require("custom_voice.preview.read"))):
        content = read_protected_preview(preview_root=preview_root, preview_id=preview_id, expected_sha256=expected_sha256, scopes={"custom_voice.preview.read"})
        return Response(content, media_type="audio/wav", headers={"ETag": f'"sha256:{expected_sha256}"', "Cache-Control": "private, no-store"})

    def mutation_route(name: str, scope: str, model: type[BaseModel]):
        async def route(request: Request, _caller: str = Depends(require(scope))):
            try:
                payload = model.model_validate_json(await request.body())
            except ValueError:
                return safe_error("request_invalid", 422)
            handler = handlers.get(name)
            if handler is None:
                return safe_error("operation_unavailable", 503)
            return handler(payload.model_dump())
        return route

    @app.get("/internal/v1/custom-voice-registry")
    async def registry(_caller: str = Depends(require("custom_voice.read"))):
        if registry_reader is None:
            return safe_error("operation_unavailable", 503)
        return registry_reader()

    @app.get("/internal/v1/custom-voice-deletions/{request_id}")
    async def deletion(request_id: str, _caller: str = Depends(require("custom_voice.read"))):
        if deletion_reader is None or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id):
            return safe_error("deletion_missing", 404)
        return deletion_reader(request_id)

    app.add_api_route("/internal/v1/custom-voice-registry/stage", mutation_route("stage", "custom_voice.activate", Mutation), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/activate", mutation_route("activate", "custom_voice.activate", Activation), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/rollback", mutation_route("rollback", "custom_voice.activate", Activation), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/retire", mutation_route("retire", "custom_voice.activate", Mutation), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-deletions", mutation_route("delete", "custom_voice.delete", Mutation), methods=["POST"], status_code=202)
    return app
