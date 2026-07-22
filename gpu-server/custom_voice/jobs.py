"""Durable custom-voice job/event queue with idempotent submission."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
STATES = {
    "queued", "validating", "preprocessing", "building", "evaluating",
    "succeeded", "failed", "cancelling", "cancelled", "deleting",
}
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
INFLIGHT_STATES = {"validating", "preprocessing", "building", "evaluating", "cancelling"}
TRANSITIONS = {
    "queued": {"validating", "cancelling", "failed"},
    "validating": {"preprocessing", "failed", "cancelling"},
    "preprocessing": {"building", "failed", "cancelling"},
    "building": {"evaluating", "failed", "cancelling"},
    "evaluating": {"succeeded", "failed", "cancelling"},
    "cancelling": {"cancelled", "failed"},
    "succeeded": {"deleting"},
    "failed": {"deleting"},
    "cancelled": {"deleting"},
    "deleting": set(),
}


class JobError(ValueError):
    """Safe durable-job failure."""


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        self.path = path
        self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                caller_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                intake_id TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                builder_profile TEXT NOT NULL,
                callback_id TEXT,
                state TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                safe_result_json TEXT,
                UNIQUE(caller_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS job_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                state TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS job_events_job_id ON job_events(job_id, event_id);
            """
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        if "callback_id" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN callback_id TEXT")
        os.chmod(path, 0o600)

    def close(self) -> None:
        self.connection.close()

    def create_job(
        self,
        *,
        caller_id: str,
        idempotency_key: str,
        intake_id: str,
        manifest_sha256: str,
        builder_profile: str,
        callback_id: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        for value in (caller_id, idempotency_key, intake_id, builder_profile):
            if not ID_RE.fullmatch(value):
                raise JobError("job_identifier_invalid")
        if not SHA256_RE.fullmatch(manifest_sha256):
            raise JobError("manifest_digest_invalid")
        if callback_id is not None and not ID_RE.fullmatch(callback_id):
            raise JobError("callback_id_invalid")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT * FROM jobs WHERE caller_id = ? AND idempotency_key = ?",
                (caller_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["manifest_sha256"] != manifest_sha256 or existing["intake_id"] != intake_id or existing["builder_profile"] != builder_profile or existing["callback_id"] != callback_id:
                    raise JobError("idempotency_conflict")
                self.connection.execute("COMMIT")
                return dict(existing), False
            job_id = "cvj_" + uuid.uuid4().hex
            self.connection.execute(
                "INSERT INTO jobs(job_id,caller_id,idempotency_key,intake_id,manifest_sha256,builder_profile,callback_id,state) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, caller_id, idempotency_key, intake_id, manifest_sha256, builder_profile, callback_id, "queued"),
            )
            self.connection.execute(
                "INSERT INTO job_events(job_id,state,reason) VALUES(?,?,?)",
                (job_id, "queued", "job_created"),
            )
            row = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            self.connection.execute("COMMIT")
            return dict(row), True
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def transition(self, job_id: str, state: str, reason: str, safe_result: dict[str, object] | None = None) -> dict[str, object]:
        if state not in STATES or not ID_RE.fullmatch(reason):
            raise JobError("job_transition_invalid")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not current:
                raise JobError("job_missing")
            if state not in TRANSITIONS[current["state"]]:
                raise JobError("job_transition_invalid")
            result_json = json.dumps(safe_result, sort_keys=True, separators=(",", ":")) if safe_result is not None else current["safe_result_json"]
            self.connection.execute(
                "UPDATE jobs SET state=?, safe_result_json=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (state, result_json, job_id),
            )
            self.connection.execute("INSERT INTO job_events(job_id,state,reason) VALUES(?,?,?)", (job_id, state, reason))
            updated = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            self.connection.execute("COMMIT")
            return dict(updated)
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def claim_next(self) -> dict[str, object] | None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at, job_id LIMIT 1").fetchone()
            if not row:
                self.connection.execute("COMMIT")
                return None
            self.connection.execute(
                "UPDATE jobs SET state='validating',attempt=attempt+1,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (row["job_id"],),
            )
            self.connection.execute("INSERT INTO job_events(job_id,state,reason) VALUES(?,?,?)", (row["job_id"], "validating", "worker_claimed"))
            claimed = self.connection.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            self.connection.execute("COMMIT")
            return dict(claimed)
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def recover_inflight(self) -> int:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self.connection.execute(
                f"SELECT job_id,state FROM jobs WHERE state IN ({','.join('?' for _ in INFLIGHT_STATES)})",
                tuple(sorted(INFLIGHT_STATES)),
            ).fetchall()
            for row in rows:
                target = "cancelled" if row["state"] == "cancelling" else "queued"
                self.connection.execute("UPDATE jobs SET state=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (target, row["job_id"]))
                self.connection.execute("INSERT INTO job_events(job_id,state,reason) VALUES(?,?,?)", (row["job_id"], target, "service_recovered"))
            self.connection.execute("COMMIT")
            return len(rows)
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def get_job(self, job_id: str) -> dict[str, object]:
        row = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise JobError("job_missing")
        return dict(row)

    def events(self, job_id: str) -> list[dict[str, object]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT event_id,state,reason,created_at FROM job_events WHERE job_id=? ORDER BY event_id", (job_id,)
        )]
