"""
scraper.py

Playwright-based scraper for LinkedIn Jobs search result pages.

Design notes:
- We reuse a single browser context across scan cycles (created once in
  main.py and passed in) rather than launching a fresh browser every time.
  Constantly relaunching browsers is slower and more bot-like.
- We add small randomized delays around navigation to avoid a perfectly
  metronomic request pattern.
- Selectors are centralized as constants so that when LinkedIn changes its
  markup (it does, periodically), you only need to update them in one place.
- This scrapes the public/guest job search results. If LINKEDIN_STORAGE_STATE_PATH
  is set, the browser context will instead carry your logged-in session,
  which surfaces more results per page but carries higher account-flagging
  risk. Use at your own discretion.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

# Centralized selectors — update here if LinkedIn changes its markup.
JOB_CARD_SELECTOR = "div.base-card, li[data-occludable-job-id]"
TITLE_SELECTOR = "h3.base-search-card__title, .base-search-card__title"
COMPANY_SELECTOR = "h4.base-search-card__subtitle, .base-search-card__subtitle"
LOCATION_SELECTOR = ".job-search-card__location"
LINK_SELECTOR = "a.base-card__full-link, a.base-card__full-link[href]"

JOB_ID_PATTERN = re.compile(r"(?:jobs/view/|currentJobId=)(\d+)")


@dataclass(frozen=True)
class ScrapedJob:
    """A job listing as extracted from the page, before DB/filter logic."""

    linkedin_job_id: str
    title: str
    company: str
    location: str
    url: str


async def _human_delay(min_ms: int = 400, max_ms: int = 1200) -> None:
    """Small randomized pause to avoid perfectly uniform request timing."""
    import asyncio

    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


def _extract_job_id(url: str) -> str | None:
    match = JOB_ID_PATTERN.search(url)
    return match.group(1) if match else None


async def _safe_text(card, selector: str) -> str:
    """Extract inner text for a selector, returning '' if not found."""
    try:
        el = card.locator(selector).first
        if await el.count() == 0:
            return ""
        return (await el.inner_text()).strip()
    except PlaywrightTimeoutError:
        return ""


async def scrape_search(page: Page, search_url: str) -> list[ScrapedJob]:
    """
    Navigate to a LinkedIn Jobs search URL and extract the visible job
    listings on the first results page.

    Returns an empty list (rather than raising) on recoverable failures like
    a page that didn't load any cards, so a single bad scan doesn't crash
    the whole loop. Raises for genuine navigation errors so the caller can
    log them.
    """
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    await _human_delay()

    # Give the job cards time to render; LinkedIn's guest pages are mostly
    # server-rendered but still benefit from a short settle time.
    try:
        await page.wait_for_selector(JOB_CARD_SELECTOR, timeout=8_000)
    except PlaywrightTimeoutError:
        # No cards found — could be zero results, could be a layout change,
        # could be a soft block page. Caller decides what to do with an
        # empty list (it will just log 0 jobs checked).
        return []

    # Scroll a bit to trigger any lazy-loaded cards, human-like.
    await page.mouse.wheel(0, 1500)
    await _human_delay(300, 800)

    cards = page.locator(JOB_CARD_SELECTOR)
    count = await cards.count()

    results: list[ScrapedJob] = []
    for i in range(count):
        card = cards.nth(i)

        href = ""
        try:
            link_el = card.locator(LINK_SELECTOR).first
            if await link_el.count() > 0:
                href = await link_el.get_attribute("href") or ""
        except PlaywrightTimeoutError:
            pass

        job_id = _extract_job_id(href)
        if not job_id:
            # Can't dedup a job without a stable ID — skip it rather than
            # risk creating duplicate notifications.
            continue

        title = await _safe_text(card, TITLE_SELECTOR)
        company = await _safe_text(card, COMPANY_SELECTOR)
        location = await _safe_text(card, LOCATION_SELECTOR)

        if not title:
            # A card with no title is almost certainly a rendering artifact,
            # not a real listing — skip it.
            continue

        # Normalize the URL to a canonical, tracking-parameter-free form.
        clean_url = f"https://www.linkedin.com/jobs/view/{job_id}/"

        results.append(
            ScrapedJob(
                linkedin_job_id=job_id,
                title=title,
                company=company or "Unknown",
                location=location or "Unknown",
                url=clean_url,
            )
        )

    return results
