"""Contract views of durable jobs, and callback notification on transitions."""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime

from .callbacks import CallbackDispatcher, CallbackError
from .jobs import JobStore

logger = logging.getLogger(__name__)
SAFE_CODE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def _timestamp(value: object) -> str:
    """SQLite CURRENT_TIMESTAMP (UTC, 'YYYY-MM-DD HH:MM:SS') as RFC 3339."""

    text = str(value)
    try:
        moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return text
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_code(value: object, fallback: str = "build_failed") -> str:
    code = str(value or "")
    if 3 <= len(code) <= 64 and code[0].isalpha() and set(code) <= SAFE_CODE_CHARS:
        return code
    return fallback


def build_job_view(job: dict, events: list[dict] | None = None) -> dict:
    """Serialize a JobStore row to the contract's BuildJob, never raw columns."""

    stored = json.loads(job["safe_result_json"]) if job.get("safe_result_json") else {}
    view: dict[str, object] = {
        "schema_version": "custom-voice-build-job.v1",
        "job_id": job["job_id"],
        "state": job["state"],
        "intake_id": job["intake_id"],
        "manifest_sha256": job["manifest_sha256"],
        "builder_profile": job["builder_profile"],
        "created_at": _timestamp(job["created_at"]),
        "updated_at": _timestamp(job["updated_at"]),
        "result": stored.get("result") if job["state"] == "succeeded" else None,
        "error": None,
    }
    if job["state"] in {"failed", "cancelled"} and stored.get("error"):
        error = stored["error"]
        status = error.get("status") if isinstance(error.get("status"), int) and 400 <= error["status"] <= 599 else 500
        view["error"] = {"type": "about:blank", "code": safe_code(error.get("code")), "status": status}
    if events is not None:
        view["events"] = [
            {"event_id": event["event_id"], "state": event["state"], "reason": event.get("reason"), "created_at": _timestamp(event["created_at"])}
            for event in events
        ]
    return view


class JobNotifier:
    """Deliver the latest job event to its allow-listed callback, best effort.

    Delivery never blocks or fails a transition: the job is authoritative and
    HeartCode reconciles by reading it, so a lost callback costs latency only.
    """

    def __init__(self, jobs: JobStore, dispatcher: CallbackDispatcher | None, *, background: bool = True):
        self.jobs = jobs
        self.dispatcher = dispatcher
        self.background = background

    def notify(self, job_id: str) -> None:
        if self.dispatcher is None:
            return
        job = self.jobs.get_job(job_id)
        callback_id = job.get("callback_id")
        if not callback_id:
            return
        events = self.jobs.events(job_id)
        if not events:
            return
        latest = events[-1]
        event = {
            "schema_version": "custom-voice-callback.v1",
            "callback_id": callback_id,
            "event_id": latest["event_id"],
            "job_id": job_id,
            "state": latest["state"],
            "occurred_at": _timestamp(latest["created_at"]),
        }
        if latest.get("reason"):
            event["reason"] = safe_code(latest["reason"], "state_changed")
        if self.background:
            threading.Thread(target=self._deliver, args=(callback_id, event), daemon=True).start()
        else:
            self._deliver(callback_id, event)

    def _deliver(self, callback_id: str, event: dict) -> None:
        try:
            outcome = self.dispatcher.deliver(callback_id, event)
        except CallbackError as error:
            logger.warning("custom_voice_callback_rejected", extra={"code": str(error), "job_id": event["job_id"]})
            return
        except Exception:  # noqa: BLE001 - best effort, content-free
            logger.warning("custom_voice_callback_error", extra={"job_id": event["job_id"]})
            return
        if outcome.get("outcome") != "delivered":
            logger.warning("custom_voice_callback_undelivered", extra={"job_id": event["job_id"], "status": outcome.get("status")})
