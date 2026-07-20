"""
main.py

Entry point for the job alert engine. Run this as a long-lived process
(directly, via systemd, or in a Docker container — see deploy/).

For each configured search, on a fixed interval, this:
  1. Scrapes the current results with Playwright.
  2. Filters out jobs already in the database (dedup) and jobs that don't
     match the search's include/exclude keyword filters.
  3. Inserts newly-seen jobs and emails a notification for each.
  4. Logs the scan (time, jobs checked, new jobs found) for the dashboard.

Note: GitHub Actions is not a good fit for "check every 1-2 minutes"
continuous monitoring — its scheduled workflows have a minimum interval of
5 minutes and jobs are billed/limited in duration. For true 1-2 minute
polling, run this on a small VPS (see deploy/job-alerts.service) or any
always-on machine. See README for details.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from playwright.async_api import async_playwright, BrowserContext

from config import AppConfig, SearchConfig, load_app_config, load_searches
from database import Database, Job
from notifier import send_job_notification
from scraper import scrape_search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("job_alerts")


async def run_one_scan(
    context: BrowserContext,
    db: Database,
    config: AppConfig,
    search: SearchConfig,
) -> None:
    """Scrape a single search, persist new jobs, and notify about them."""
    page = await context.new_page()
    try:
        scraped_jobs = await scrape_search(page, search.url)
    except Exception as exc:  # noqa: BLE001 - log and move on, don't crash the loop
        logger.error("Scan failed for '%s': %s", search.name, exc)
        db.log_scan(search.name, jobs_checked=0, new_jobs_found=0, error=str(exc))
        return
    finally:
        await page.close()

    new_count = 0
    for scraped in scraped_jobs:
        if db.job_exists(scraped.linkedin_job_id):
            continue  # already seen -> never re-notify

        if not search.matches_filters(scraped.title):
            continue  # doesn't pass this search's keyword filters

        job = Job(
            linkedin_job_id=scraped.linkedin_job_id,
            search_name=search.name,
            title=scraped.title,
            company=scraped.company,
            location=scraped.location,
            url=scraped.url,
            first_seen_at=datetime.now(timezone.utc).isoformat(),
        )
        db.insert_job(job)
        new_count += 1

        success, detail = send_job_notification(config, job)
        db.log_notification(job.linkedin_job_id, "sent" if success else "failed", detail)
        if success:
            logger.info("Notified: %s at %s (%s)", job.title, job.company, search.name)
        else:
            logger.warning("Notification failed for %s: %s", job.title, detail)

    db.log_scan(search.name, jobs_checked=len(scraped_jobs), new_jobs_found=new_count)
    logger.info(
        "Scanned '%s': %d jobs checked, %d new", search.name, len(scraped_jobs), new_count
    )


async def scan_cycle(context: BrowserContext, db: Database, config: AppConfig) -> None:
    """Run one full cycle: scan every configured search, one after another."""
    searches = load_searches()  # reloaded each cycle so edits take effect without a restart
    for search in searches:
        await run_one_scan(context, db, config, search)


async def main() -> None:
    config = load_app_config()
    db = Database(config.database_path)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context_kwargs: dict = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1366, "height": 900},
        }
        if config.linkedin_storage_state_path:
            context_kwargs["storage_state"] = config.linkedin_storage_state_path

        context = await browser.new_context(**context_kwargs)

        logger.info(
            "Job alert engine started. Scanning every %d seconds.",
            config.scan_interval_seconds,
        )
        try:
            while True:
                cycle_start = asyncio.get_event_loop().time()
                await scan_cycle(context, db, config)
                elapsed = asyncio.get_event_loop().time() - cycle_start
                sleep_for = max(0.0, config.scan_interval_seconds - elapsed)
                await asyncio.sleep(sleep_for)
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
