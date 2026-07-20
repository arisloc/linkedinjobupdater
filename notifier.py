"""
notifier.py

Sends email notifications for newly discovered jobs via SMTP (works with
Gmail using an App Password — see .env.example). Kept separate from the
scraper and database so the notification channel could be swapped later
(e.g. for Slack, SMS) without touching the rest of the app.
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from tenacity import retry, stop_after_attempt, wait_exponential

from config import AppConfig
from database import Job


def _build_email_body(job: Job) -> str:
    """Plain-text email body for a single new job notification."""
    return (
        f"New job posting matching your search \"{job.search_name}\":\n\n"
        f"Title:    {job.title}\n"
        f"Company:  {job.company}\n"
        f"Location: {job.location}\n"
        f"Link:     {job.url}\n"
        f"Detected: {job.first_seen_at}\n"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
def _send_smtp(config: AppConfig, subject: str, body: str) -> None:
    """Send one email, retrying transient SMTP failures with backoff."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.email_from
    msg["To"] = config.email_to

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as server:
        server.starttls()
        server.login(config.smtp_username, config.smtp_password)
        server.send_message(msg)


def send_job_notification(config: AppConfig, job: Job) -> tuple[bool, str]:
    """
    Send a notification email for a newly found job.

    Returns (success, detail) so the caller can log the outcome to the
    notifications table without the notifier needing to know about the DB.
    """
    subject = f"New job: {job.title} at {job.company}"
    body = _build_email_body(job)

    try:
        _send_smtp(config, subject, body)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001 - we want to catch and log any SMTP failure
        return False, f"{type(exc).__name__}: {exc}"
