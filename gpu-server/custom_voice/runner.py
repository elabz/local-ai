"""Host-side build runner: drives queued jobs through the existing pipeline.

    python3 -m custom_voice.runner --private-root /srv/local-ai/private

Runs on the Pea host as the custom-voice service UID (a systemd unit, see
OPERATIONS.md), not inside the control-plane container: launching the pinned
worker and compatibility containers needs Docker, and neither the private API
nor any builder container is ever given the Docker socket. It shares the job
queue with the API through the SQLite file under the private root.

Per job: validating (claimed) -> preprocessing (`intake.prepare_workspace`) ->
building (`run_worker.sh`) -> evaluating (`run_postbuild.sh`: seal, Kokoro
compatibility, held-out evaluation; then `run_sbom.sh`; then
`preview.stage_for_review`) -> succeeded with a contract `BuildResult`.
Any failure ends the job `failed` with a safe reason code; a cancellation
request is honoured between phases and, while the worker runs, by the worker's
own `cancel.requested` file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .intake import IntakeError, prepare_workspace
from .job_view import JobNotifier, safe_code
from .jobs import JobStore
from .lifecycle import PREVIEWS_FILE
from .preview import PreviewError, stage_for_review

logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent

# run(argv, env, poll) -> (returncode, stdout). poll() is called while the
# command runs; the default implementation calls it every few seconds.
RunCommand = Callable[[list[str], dict[str, str], Callable[[], None]], tuple[int, str]]


class BuildFailure(RuntimeError):
    def __init__(self, code: str, status: int = 500):
        super().__init__(code)
        self.code = safe_code(code)
        self.status = status


class Cancelled(RuntimeError):
    pass


def subprocess_run(argv: list[str], env: dict[str, str], poll: Callable[[], None], interval: float = 5.0) -> tuple[int, str]:
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    while True:
        try:
            stdout, _ = process.communicate(timeout=interval)
            return process.returncode, stdout
        except subprocess.TimeoutExpired:
            poll()


def last_json_line(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


@dataclass
class RunnerConfig:
    private_root: Path
    worker_image: str
    worker_image_digest: str
    compat_image: str
    runtime_image: str
    script_dir: Path = SCRIPT_DIR
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def intake(self) -> Path:
        return self.private_root / "custom-voice-intake"

    @property
    def workspaces(self) -> Path:
        return self.private_root / "custom-voice-workspaces"

    @property
    def results(self) -> Path:
        return self.private_root / "custom-voice-results"

    @property
    def artifacts(self) -> Path:
        return self.private_root / "custom-voice-artifacts"

    @property
    def registry(self) -> Path:
        return self.private_root / "custom-voice-registry" / "registry.json"


class Runner:
    def __init__(self, jobs: JobStore, config: RunnerConfig, notifier: JobNotifier, *, run: RunCommand = subprocess_run, prepare=prepare_workspace, stage=stage_for_review):
        self.jobs = jobs
        self.config = config
        self.notifier = notifier
        self.run_command = run
        self.prepare = prepare
        self.stage = stage

    # -- state helpers ---------------------------------------------------------

    def _move(self, job_id: str, state: str, reason: str, safe_result: dict | None = None) -> None:
        self.jobs.transition(job_id, state, reason, safe_result)
        self.notifier.notify(job_id)

    def _check_cancel(self, job_id: str) -> None:
        if self.jobs.get_job(job_id)["state"] == "cancelling":
            raise Cancelled()

    def _env(self, job_id: str, **values: str) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "PYTHONPATH": str(self.config.script_dir.parent),
            "CUSTOM_VOICE_JOB_ID": job_id,
            "CUSTOM_VOICE_PRIVATE_ROOT": str(self.config.private_root),
            "CUSTOM_VOICE_WORKER_IMAGE": self.config.worker_image,
            "CUSTOM_VOICE_WORKER_IMAGE_DIGEST": self.config.worker_image_digest,
            "CUSTOM_VOICE_COMPAT_IMAGE": self.config.compat_image,
            "CUSTOM_VOICE_RUNTIME_IMAGE": self.config.runtime_image,
        }
        env.update(self.config.extra_env)
        env.update(values)
        return env

    def _script(self, job_id: str, name: str, failure: str, **values: str) -> dict:
        def poll() -> None:
            # The worker stops itself when this file appears (worker.py).
            if self.jobs.get_job(job_id)["state"] == "cancelling":
                marker = self.config.results / job_id / "cancel.requested"
                if marker.parent.is_dir():
                    marker.touch(mode=0o600, exist_ok=True)

        code, stdout = self.run_command(["/bin/sh", str(self.config.script_dir / name)], self._env(job_id, **values), poll)
        outcome = last_json_line(stdout)
        if outcome.get("outcome") == "cancelled":
            raise Cancelled()
        if code != 0 or outcome.get("outcome") in {"failed", "reject"}:
            raise BuildFailure(str(outcome.get("reason") or failure))
        return outcome

    # -- one job ---------------------------------------------------------------

    def run_job(self, job: dict) -> None:
        job_id = str(job["job_id"])
        self.notifier.notify(job_id)  # validating (worker_claimed)
        try:
            manifest = json.loads((self.config.intake / str(job["intake_id"]) / "manifest.json").read_text(encoding="utf-8"))
            stable_voice_id, version = str(manifest["stable_voice_id"]), str(manifest["version"])
        except (OSError, ValueError, KeyError):
            self._fail(job_id, BuildFailure("intake_manifest_incomplete", 422))
            return
        try:
            self._check_cancel(job_id)
            self._move(job_id, "preprocessing", "intake_validated")
            try:
                self.prepare(
                    intake_root=self.config.intake,
                    intake_id=str(job["intake_id"]),
                    expected_manifest_sha256=str(job["manifest_sha256"]),
                    workspace_root=self.config.workspaces,
                    job_id=job_id,
                    seed=secrets.randbelow(2**31),
                    expected_uid=os.getuid(),
                )
            except IntakeError as error:
                raise BuildFailure(str(error), 422) from error
            self._check_cancel(job_id)
            self._move(job_id, "building", "workspace_prepared")
            (self.config.results / job_id).mkdir(mode=0o700, parents=True, exist_ok=True)
            self._script(job_id, "run_worker.sh", "worker_failed")
            self._check_cancel(job_id)
            self._move(job_id, "evaluating", "build_completed")
            self._script(job_id, "run_postbuild.sh", "postbuild_failed", CUSTOM_VOICE_STABLE_ID=stable_voice_id, CUSTOM_VOICE_VERSION=version)
            result = self._seal_review(job_id, stable_voice_id, version)
        except Cancelled:
            self._move(job_id, "cancelled", "cancelled_by_request", {"error": {"code": "build_cancelled", "status": 409}})
            return
        except BuildFailure as failure:
            self._fail(job_id, failure)
            return
        except Exception:
            logger.exception("custom_voice_runner_unexpected", extra={"job_id": job_id})
            self._fail(job_id, BuildFailure("runner_internal_error"))
            return
        self._move(job_id, "succeeded", "review_staged", {"result": result})

    def _fail(self, job_id: str, failure: BuildFailure) -> None:
        state = self.jobs.get_job(job_id)["state"]
        if state in {"succeeded", "failed", "cancelled"}:
            return
        self._move(job_id, "failed", failure.code, {"error": {"code": failure.code, "status": failure.status}})

    def _seal_review(self, job_id: str, stable_voice_id: str, version: str) -> dict:
        version_root = self.config.artifacts / stable_voice_id / version
        result_root = self.config.results / job_id
        manifest_path = version_root / "manifest.json"
        try:
            artifact_manifest_bytes = manifest_path.read_bytes()
            artifact_manifest = json.loads(artifact_manifest_bytes)
            artifact = artifact_manifest["artifact"]
            evaluation = json.loads((result_root / "evaluation.json").read_text(encoding="utf-8"))
            compatibility = json.loads((result_root / "compatibility.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as error:
            raise BuildFailure("postbuild_output_missing") from error
        sbom = self._script(
            job_id, "run_sbom.sh", "sbom_failed",
            CUSTOM_VOICE_STABLE_ID=stable_voice_id, CUSTOM_VOICE_VERSION=version, CUSTOM_VOICE_ARTIFACT_SHA256=str(artifact["sha256"]),
        )
        if not isinstance(sbom.get("sbom_sha256"), str) or not isinstance(sbom.get("unresolved_license_count"), int):
            raise BuildFailure("sbom_failed")
        try:
            staged = self.stage(
                registry_path=self.config.registry,
                artifact_manifest_path=manifest_path,
                evaluation_path=result_root / "evaluation.json",
                compatibility_path=result_root / "compatibility.json",
            )
        except PreviewError as error:
            raise BuildFailure(str(error)) from error
        previews = staged["previews"][:16]
        previews_path = version_root / PREVIEWS_FILE
        previews_path.write_text(json.dumps([item["preview_id"] for item in previews]), encoding="utf-8")
        previews_path.chmod(0o600)
        return {
            "artifact": {
                "stable_voice_id": stable_voice_id,
                "version": version,
                "artifact_sha256": artifact["sha256"],
                "artifact_size": artifact["size"],
                "artifact_manifest_sha256": hashlib.sha256(artifact_manifest_bytes).hexdigest(),
            },
            "sbom": {"sha256": sbom["sbom_sha256"], "unresolved_license_count": sbom["unresolved_license_count"]},
            "evaluation": {
                "objective_outcome": evaluation["objective_outcome"],
                "mean_word_error_rate": evaluation["mean_word_error_rate"],
                "mean_speaker_similarity": evaluation["mean_speaker_similarity"],
                "human_naturalness_outcome": evaluation.get("human_naturalness_outcome", "pending"),
            },
            "compatibility": "pass" if compatibility.get("outcome") == "pass" else "reject",
            "previews": previews,
        }

    # -- loop ----------------------------------------------------------------

    def run_once(self) -> bool:
        job = self.jobs.claim_next()
        if job is None:
            return False
        self.run_job(job)
        return True

    def serve(self, idle_seconds: float = 10.0) -> None:
        for job_id in self._recover():
            self.notifier.notify(job_id)
        while True:
            if not self.run_once():
                time.sleep(idle_seconds)

    def _recover(self) -> list[str]:
        before = {row["job_id"] for row in self.jobs.connection.execute("SELECT job_id FROM jobs WHERE state IN ('validating','preprocessing','building','evaluating','cancelling')")}
        self.jobs.recover_inflight()
        return sorted(before)


def main() -> None:
    import httpx

    from .callbacks import CallbackDispatcher
    from .service import PrivateRoot, load_callback_targets

    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="run at most one job and exit")
    arguments = parser.parse_args()
    os.umask(0o077)
    paths = PrivateRoot(arguments.private_root)
    config = RunnerConfig(
        private_root=arguments.private_root,
        worker_image=os.environ["CUSTOM_VOICE_WORKER_IMAGE"],
        worker_image_digest=os.environ["CUSTOM_VOICE_WORKER_IMAGE_DIGEST"],
        compat_image=os.environ["CUSTOM_VOICE_COMPAT_IMAGE"],
        runtime_image=os.environ.get("CUSTOM_VOICE_RUNTIME_IMAGE", "ghcr.io/remsky/kokoro-fastapi-gpu:v0.6.0@sha256:560e5ba33e78597cf35d266a5591c3ce7558dce318b3019fb6d94e28b466080b"),
    )
    jobs = JobStore(paths.jobs_db)
    targets = load_callback_targets(paths.control / "callback-targets.json")
    notifier = JobNotifier(jobs, CallbackDispatcher(targets, httpx.post) if targets else None, background=False)
    runner = Runner(jobs, config, notifier)
    if arguments.once:
        runner.run_once()
    else:
        runner.serve()


if __name__ == "__main__":
    main()
