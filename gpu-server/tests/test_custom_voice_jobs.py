import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.jobs import JobError, JobStore


def create(store: JobStore, digest: str = "a" * 64):
    return store.create_job(caller_id="heartcode-prod", idempotency_key="request-001", intake_id="bench-speaker-001-v1", manifest_sha256=digest, builder_profile="kvoicewalk-multireference.v1")


def test_identical_retry_returns_original_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    first, created = create(store)
    second, retried_created = create(store)
    assert created is True
    assert retried_created is False
    assert second["job_id"] == first["job_id"]
    assert len(store.events(first["job_id"])) == 1


def test_idempotency_key_reuse_with_different_digest_is_rejected(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    create(store)
    with pytest.raises(JobError, match="idempotency_conflict"):
        create(store, "b" * 64)


def test_claim_and_restart_recovery_are_durable(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    job, _ = create(store)
    claimed = store.claim_next()
    assert claimed["state"] == "validating"
    assert claimed["attempt"] == 1
    store.close()

    reopened = JobStore(path)
    assert reopened.recover_inflight() == 1
    assert reopened.get_job(job["job_id"])["state"] == "queued"
    assert reopened.events(job["job_id"])[-1]["reason"] == "service_recovered"


def test_invalid_transition_does_not_append_event(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job, _ = create(store)
    before = store.events(job["job_id"])
    with pytest.raises(JobError, match="job_transition_invalid"):
        store.transition(job["job_id"], "succeeded", "invalid_skip")
    assert store.events(job["job_id"]) == before
