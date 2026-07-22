"""Private FastAPI boundary for custom-voice build and lifecycle operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, RequestAuthenticator
from .jobs import JobError, JobStore
from .preview import PreviewError, read_protected_preview


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
    stable_voice_id: str
    version: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def safe_error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"type": "about:blank", "code": code, "status": status}, status_code=status, media_type="application/problem+json")


def create_app(
    *,
    jobs: JobStore,
    authenticator: RequestAuthenticator,
    preview_root: Path,
    mutation_handlers: dict[str, Callable[[dict], dict]] | None = None,
) -> FastAPI:
    app = FastAPI(title="Private Custom Voice Control Plane", docs_url=None, redoc_url=None, openapi_url=None)
    handlers = mutation_handlers or {}

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

    @app.post("/internal/v1/custom-voice-builds", status_code=202)
    async def create_build(payload: CreateBuild, idempotency_key: str = Header(alias="Idempotency-Key"), caller: str = Depends(require("custom_voice.build"))):
        callback_id = payload.callback.get("callback_id") if payload.callback else None
        job, _created = jobs.create_job(caller_id=caller, idempotency_key=idempotency_key, intake_id=payload.intake_id, manifest_sha256=payload.manifest_sha256, builder_profile=payload.builder_profile, callback_id=callback_id)
        return {"schema_version": "custom-voice-build-job.v1", **job}

    @app.get("/internal/v1/custom-voice-builds/{job_id}")
    async def get_build(job_id: str, _caller: str = Depends(require("custom_voice.read"))):
        job = jobs.get_job(job_id)
        events = jobs.events(job_id)
        return {"schema_version": "custom-voice-build-job.v1", **job, "events": events}

    @app.post("/internal/v1/custom-voice-builds/{job_id}/cancel", status_code=202)
    async def cancel_build(job_id: str, _caller: str = Depends(require("custom_voice.build"))):
        return {"schema_version": "custom-voice-build-job.v1", **jobs.transition(job_id, "cancelling", "cancellation_requested")}

    @app.get("/internal/v1/custom-voice-previews/{preview_id}")
    async def preview(preview_id: str, expected_sha256: str, _caller: str = Depends(require("custom_voice.preview.read"))):
        content = read_protected_preview(preview_root=preview_root, preview_id=preview_id, expected_sha256=expected_sha256, scopes={"custom_voice.preview.read"})
        return Response(content, media_type="audio/wav", headers={"ETag": f'"sha256:{expected_sha256}"', "Cache-Control": "private, no-store"})

    def mutation_route(name: str, scope: str):
        async def route(payload: Mutation, _caller: str = Depends(require(scope))):
            handler = handlers.get(name)
            if handler is None:
                return safe_error("operation_unavailable", 503)
            return handler(payload.model_dump())
        return route

    app.add_api_route("/internal/v1/custom-voice-registry/stage", mutation_route("stage", "custom_voice.activate"), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/activate", mutation_route("activate", "custom_voice.activate"), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/rollback", mutation_route("rollback", "custom_voice.activate"), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-registry/retire", mutation_route("retire", "custom_voice.activate"), methods=["POST"])
    app.add_api_route("/internal/v1/custom-voice-deletions", mutation_route("delete", "custom_voice.delete"), methods=["POST"], status_code=202)
    return app
