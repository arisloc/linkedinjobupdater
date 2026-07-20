"""
config.py

Centralized configuration for the job alert application.

Two sources of configuration:
1. Environment variables (.env) — secrets and runtime tuning.
2. searches.json — the list of saved LinkedIn searches to monitor, plus
   per-search keyword include/exclude filters.

Keeping these separate means you never need to touch code (or commit
secrets) to add a new search or change your scan interval.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a .env file in the project root, if present.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SearchConfig:
    """A single saved LinkedIn Jobs search to monitor."""

    name: str
    url: str
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)

    def matches_filters(self, title: str) -> bool:
        """
        Decide whether a job title passes this search's keyword filters.

        Logic:
        - If include_keywords is non-empty, at least one must appear in the
          title (case-insensitive).
        - If any exclude_keyword appears in the title, the job is rejected
          regardless of include matches.
        """
        title_lower = title.lower()

        if self.exclude_keywords and any(
            kw.lower() in title_lower for kw in self.exclude_keywords
        ):
            return False

        if self.include_keywords:
            return any(kw.lower() in title_lower for kw in self.include_keywords)

        # No include filter defined -> everything passes (subject to exclude above).
        return True


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration assembled from environment variables."""

    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    email_to: str

    scan_interval_seconds: int
    database_path: str
    linkedin_storage_state_path: str | None

    dashboard_host: str
    dashboard_port: int


def load_app_config() -> AppConfig:
    """Read and validate required environment variables into an AppConfig."""

    def _require(name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(
                f"Missing required environment variable '{name}'. "
                f"Copy .env.example to .env and fill it in."
            )
        return value

    storage_state = os.environ.get("LINKEDIN_STORAGE_STATE_PATH", "").strip()

    return AppConfig(
        smtp_host=_require("SMTP_HOST"),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_username=_require("SMTP_USERNAME"),
        smtp_password=_require("SMTP_PASSWORD"),
        email_from=_require("EMAIL_FROM"),
        email_to=_require("EMAIL_TO"),
        scan_interval_seconds=int(os.environ.get("SCAN_INTERVAL_SECONDS", "90")),
        database_path=os.environ.get("DATABASE_PATH", "job_alerts.db"),
        linkedin_storage_state_path=storage_state or None,
        dashboard_host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
        dashboard_port=int(os.environ.get("DASHBOARD_PORT", "8000")),
    )


def load_searches(path: str | Path = PROJECT_ROOT / "searches.json") -> list[SearchConfig]:
    """Load the list of saved searches from searches.json."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create it with at least one search (see README)."
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    searches = [
        SearchConfig(
            name=item["name"],
            url=item["url"],
            include_keywords=item.get("include_keywords", []),
            exclude_keywords=item.get("exclude_keywords", []),
        )
        for item in raw
    ]

    if not searches:
        raise ValueError(f"{path} is empty — add at least one search.")

    return searches
