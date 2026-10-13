import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.intake import IntakeError
from custom_voice.job_view import JobNotifier, build_job_view
from custom_voice.jobs import JobStore
from custom_voice.lifecycle import PREVIEWS_FILE
from custom_voice.runner import Runner, RunnerConfig

VOICE, VERSION = "custom-test-voice", "v1"


class RecordingDispatcher:
    def __init__(self):
        self.events = []

    def deliver(self, callback_id, event):
        self.events.append((callback_id, event))
        return {"outcome": "delivered", "attempts": 1, "status": 204}


class FakeScripts:
    """Stands in for run_worker.sh / run_postbuild.sh / run_sbom.sh on the host."""

    def __init__(self, root: Path, fail: str | None = None, on_worker=None):
        self.root, self.fail, self.on_worker, self.calls = root, fail, on_worker, []

    def __call__(self, argv, env, poll):
        name = Path(argv[-1]).name
        self.calls.append(name)
        if name == self.fail:
            return 2, '{"outcome":"failed","reason":"worker_gpu_reserve_low"}\n'
        if name == "run_worker.sh":
            if self.on_worker:
                self.on_worker(poll)
            return 0, '{"outcome":"succeeded"}\n'
        job = env["CUSTOM_VOICE_JOB_ID"]
        if name == "run_postbuild.sh":
            assert env["CUSTOM_VOICE_STABLE_ID"] == VOICE and env["CUSTOM_VOICE_VERSION"] == VERSION
            digest = hashlib.sha256(b"tensor").hexdigest()
            version_root = self.root / "custom-voice-artifacts" / VOICE / VERSION
            version_root.mkdir(parents=True)
            (version_root / "manifest.json").write_text(json.dumps({"stable_voice_id": VOICE, "version": VERSION, "language": "a", "artifact": {"sha256": digest, "size": 6}}))
            results = self.root / "custom-voice-results" / job
            preview_id = "b" * 32
            (results / "evaluation.json").write_text(json.dumps({"artifact_sha256": digest, "objective_outcome": "pass", "mean_word_error_rate": 0.05, "mean_speaker_similarity": 0.71, "samples": [{"preview_id": preview_id, "preview_sha256": "c" * 64}]}))
            (results / "compatibility.json").write_text(json.dumps({"artifact_sha256": digest, "outcome": "pass"}))
            return 0, '{"outcome":"succeeded","artifact_sha256":"%s"}\n' % digest
        if name == "run_sbom.sh":
            return 0, '{"package_count":5,"sbom_sha256":"%s","unresolved_license_count":2}\n' % ("d" * 64)
        raise AssertionError(name)


def make_runner(tmp_path: Path, scripts, prepare=None):
    """scripts(root) -> a FakeScripts bound to the private root."""
    root = tmp_path / "private"
    (root / "custom-voice-intake" / "hc-intake").mkdir(parents=True)
    manifest = json.dumps({"stable_voice_id": VOICE, "version": VERSION, "samples": []}).encode()
    (root / "custom-voice-intake" / "hc-intake" / "manifest.json").write_bytes(manifest)
    jobs = JobStore(root / "custom-voice-jobs" / "jobs.sqlite3")
    job, _ = jobs.create_job(caller_id="heartcode", idempotency_key="key-00000001", intake_id="hc-intake", manifest_sha256=hashlib.sha256(manifest).hexdigest(), builder_profile="kvoicewalk-multireference.v1", callback_id="heartcode-dev")
    dispatcher = RecordingDispatcher()
    config = RunnerConfig(private_root=root, worker_image="worker:1", worker_image_digest="e" * 64, compat_image="compat:1", runtime_image="kokoro:1")
    runner = Runner(jobs, config, JobNotifier(jobs, dispatcher, background=False), run=scripts(root), prepare=prepare or (lambda **_kwargs: {"sample_count": 10}))
    return runner, jobs, str(job["job_id"]), dispatcher, root


def test_a_queued_job_runs_the_pipeline_to_a_contract_build_result(tmp_path: Path) -> None:
    holder = {}
    runner, jobs, job_id, dispatcher, root = make_runner(tmp_path, lambda root: holder.setdefault("scripts", FakeScripts(root)))
    assert runner.run_once() is True
    job = jobs.get_job(job_id)
    assert job["state"] == "succeeded"
    view = build_job_view(job)
    result = view["result"]
    assert result["artifact"]["stable_voice_id"] == VOICE and result["artifact"]["artifact_size"] == 6
    assert result["sbom"] == {"sha256": "d" * 64, "unresolved_license_count": 2}
    assert result["evaluation"]["human_naturalness_outcome"] == "pending"
    assert result["compatibility"] == "pass"
    assert result["previews"] == [{"preview_id": "b" * 32, "sha256": "c" * 64}]
    assert holder["scripts"].calls == ["run_worker.sh", "run_postbuild.sh", "run_sbom.sh"]
    states = [event["state"] for _callback, event in dispatcher.events]
    assert states == ["validating", "preprocessing", "building", "evaluating", "succeeded"]
    assert [event["event_id"] for _callback, event in dispatcher.events] == sorted({event["event_id"] for _callback, event in dispatcher.events})
    registry = json.loads((root / "custom-voice-registry" / "registry.json").read_text())
    assert registry["voices"][VOICE]["versions"][VERSION]["state"] == "staged"
    assert json.loads((root / "custom-voice-artifacts" / VOICE / VERSION / PREVIEWS_FILE).read_text()) == ["b" * 32]


def test_worker_failure_ends_the_job_failed_with_its_safe_reason(tmp_path: Path) -> None:
    runner, jobs, job_id, _dispatcher, _root = make_runner(tmp_path, lambda root: FakeScripts(root, fail="run_worker.sh"))
    runner.run_once()
    view = build_job_view(jobs.get_job(job_id))
    assert view["state"] == "failed"
    assert view["error"] == {"type": "about:blank", "code": "worker_gpu_reserve_low", "status": 500}
    assert view["result"] is None


def test_intake_rejection_is_a_422_failure(tmp_path: Path) -> None:
    def reject(**_kwargs):
        raise IntakeError("audio_duration_invalid")

    runner, jobs, job_id, _dispatcher, _root = make_runner(tmp_path, lambda root: FakeScripts(root), prepare=reject)
    runner.run_once()
    view = build_job_view(jobs.get_job(job_id))
    assert view["error"] == {"type": "about:blank", "code": "audio_duration_invalid", "status": 422}


def test_cancellation_during_the_build_signals_the_worker_and_ends_cancelled(tmp_path: Path) -> None:
    state = {}

    def cancel_midway(poll):
        state["jobs"].transition(state["job_id"], "cancelling", "cancellation_requested")
        poll()
        state["marker"] = (state["root"] / "custom-voice-results" / state["job_id"] / "cancel.requested").exists()

    runner, jobs, job_id, _dispatcher, root = make_runner(tmp_path, lambda root: FakeScripts(root, on_worker=cancel_midway))
    state.update(jobs=jobs, job_id=job_id, root=root)
    runner.run_once()
    assert state["marker"] is True
    assert jobs.get_job(job_id)["state"] == "cancelled"
