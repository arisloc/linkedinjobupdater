"""
database.py

SQLite persistence layer. All other modules go through this file to read or
write data — nothing else should open a raw sqlite3 connection.

Schema:
    jobs           One row per unique LinkedIn job ever seen (deduped by
                    linkedin_job_id, which is stable across scans).
    scans          One row per scan cycle, used for dashboard stats.
    notifications  One row per email sent, for the notification history view.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    linkedin_job_id TEXT PRIMARY KEY,
    search_name     TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT NOT NULL,
    url             TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    search_name       TEXT NOT NULL,
    scan_time         TEXT NOT NULL,
    jobs_checked      INTEGER NOT NULL,
    new_jobs_found    INTEGER NOT NULL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    linkedin_job_id TEXT NOT NULL,
    sent_at         TEXT NOT NULL,
    status          TEXT NOT NULL,   -- 'sent' or 'failed'
    detail          TEXT,
    FOREIGN KEY (linkedin_job_id) REFERENCES jobs (linkedin_job_id)
);
"""


@dataclass(frozen=True)
class Job:
    """A single job posting."""

    linkedin_job_id: str
    search_name: str
    title: str
    company: str
    location: str
    url: str
    first_seen_at: str  # ISO 8601 timestamp


class Database:
    """Thin wrapper around a SQLite connection for this app's schema."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- jobs -----------------------------------------------------------

    def job_exists(self, linkedin_job_id: str) -> bool:
        """Return True if we've already recorded this job (dedup check)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE linkedin_job_id = ?", (linkedin_job_id,)
            ).fetchone()
            return row is not None

    def insert_job(self, job: Job) -> None:
        """Insert a newly discovered job. No-op (via INSERT OR IGNORE) if it
        somehow already exists, so this is safe to call defensively."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs
                    (linkedin_job_id, search_name, title, company, location, url, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.linkedin_job_id,
                    job.search_name,
                    job.title,
                    job.company,
                    job.location,
                    job.url,
                    job.first_seen_at,
                ),
            )

    def recent_jobs(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM jobs ORDER BY first_seen_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def total_jobs(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]

    # -- scans ------------------------------------------------------------

    def log_scan(
        self,
        search_name: str,
        jobs_checked: int,
        new_jobs_found: int,
        error: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scans (search_name, scan_time, jobs_checked, new_jobs_found, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (search_name, datetime.utcnow().isoformat(), jobs_checked, new_jobs_found, error),
            )

    def last_scan_time(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scan_time FROM scans ORDER BY scan_time DESC LIMIT 1"
            ).fetchone()
            return row["scan_time"] if row else None

    def scan_totals(self) -> tuple[int, int]:
        """Return (total jobs checked, total new jobs found) across all scans."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(jobs_checked), 0) AS checked, "
                "COALESCE(SUM(new_jobs_found), 0) AS found FROM scans"
            ).fetchone()
            return row["checked"], row["found"]

    def recent_scans(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM scans ORDER BY scan_time DESC LIMIT ?", (limit,)
            ).fetchall()

    # -- notifications ------------------------------------------------------

    def log_notification(self, linkedin_job_id: str, status: str, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notifications (linkedin_job_id, sent_at, status, detail)
                VALUES (?, ?, ?, ?)
                """,
                (linkedin_job_id, datetime.utcnow().isoformat(), status, detail),
            )

    def recent_notifications(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT n.*, j.title, j.company, j.location, j.url
                FROM notifications n
                JOIN jobs j ON j.linkedin_job_id = n.linkedin_job_id
                ORDER BY n.sent_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
