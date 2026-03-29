from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus

from core.date_parser import parse_posted_date
from core.deduplicator import make_job_id
from core.models import Job, LocationType
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from ranking.job_parser import detect_location_type
from scrapers.base import BaseScraper

# ─── JobStreet domain config ──────────────────────────────────────────────────

_DOMAINS: dict[str, str] = {
    "malaysia": "www.jobstreet.com.my",
    "indonesia": "www.jobstreet.co.id",
}

_LOCATION_DOMAIN_MAP: dict[str, str] = {
    "selangor, malaysia": "malaysia",
    "kuala lumpur, malaysia": "malaysia",
    "petaling jaya, malaysia": "malaysia",
    "malaysia": "malaysia",
    "jakarta, indonesia": "indonesia",
    "indonesia": "indonesia",
}


class JobStreetScraper(BaseScraper):
    """
    Scrapes job listings from JobStreet Malaysia (jobstreet.com.my)
    and JobStreet Indonesia (jobstreet.co.id) using Playwright.

    JobStreet is part of the SEEK group and is the dominant job board
    in Malaysia and Indonesia — high signal-to-noise for local roles.
    """

    source_name = "jobstreet"

    def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        self.log("Starting JobStreet scrape …")

        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(
                **self._get_playwright_launch_options()
            )
            context: BrowserContext = browser.new_context(
                **self._get_browser_context_options()
            )
            page: Page = context.new_page()

            # Reduce noise: block images, fonts, analytics to speed up scraping
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_()
                ),
            )

            seen_ids: set[str] = set()

            for title in self.titles:
                for location in self.all_locations:
                    domain_key = self._resolve_domain(location)
                    if not domain_key:
                        continue

                    try:
                        new_jobs = self._scrape_search(
                            page=page,
                            title=title,
                            location=location,
                            domain=_DOMAINS[domain_key],
                        )

                        # Deduplicate within this run
                        for job in new_jobs:
                            if job.id not in seen_ids:
                                seen_ids.add(job.id)
                                jobs.append(job)

                        self.log_found(len(new_jobs), title, location)

                        if len(jobs) >= self._max_jobs:
                            self.log(
                                f"Reached max_jobs limit ({self._max_jobs}). Stopping."
                            )
                            break

                    except Exception as exc:
                        self.log_error(f"Error scraping '{title}' in '{location}'", exc)

                if len(jobs) >= self._max_jobs:
                    break

            context.close()
            browser.close()

        self.log(f"Done. Total unique jobs scraped: {len(jobs)}")
        return jobs

    # ─── Search page scraper ──────────────────────────────────────────────────

    def _scrape_search(
        self,
        page: Page,
        title: str,
        location: str,
        domain: str,
    ) -> list[Job]:
        """Navigate to a JobStreet search results page and extract job listings."""
        url = self._build_search_url(domain, title, location)
        self.log(f"Navigating → {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            self.log_error(f"Navigation failed for {url}", exc)
            return []

        # Wait for job cards to appear (JobStreet uses data-automation attributes)
        try:
            page.wait_for_selector(
                '[data-automation="jobListing"], [data-automation="job-card"], article[data-job-id]',
                timeout=12_000,
            )
        except Exception:
            self.log(
                f"No job cards found on {url} (page may be empty or changed layout)"
            )
            return []

        self._delay()

        jobs = self._extract_jobs_from_page(page, domain, title, location)

        # Attempt to get page 2 for popular titles
        if len(jobs) < 20:
            return jobs

        try:
            page2_url = url + "&page=2"
            page.goto(page2_url, wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_selector(
                '[data-automation="jobListing"], [data-automation="job-card"], article[data-job-id]',
                timeout=10_000,
            )
            self._delay()
            page2_jobs = self._extract_jobs_from_page(page, domain, title, location)
            jobs.extend(page2_jobs)
        except Exception:
            pass  # Page 2 is a bonus — don't fail if unavailable

        return jobs

    # ─── Job extraction ───────────────────────────────────────────────────────

    def _extract_jobs_from_page(
        self,
        page: Page,
        domain: str,
        search_title: str,
        search_location: str,
    ) -> list[Job]:
        """Extract all job cards visible on the current page."""
        jobs: list[Job] = []

        # JobStreet uses several possible card selectors across A/B tests
        card_selectors = [
            '[data-automation="jobListing"]',
            "article[data-job-id]",
            '[data-testid="job-card"]',
            'div[class*="JobCard"]',
            'div[class*="job-card"]',
        ]

        cards = []
        for selector in card_selectors:
            cards = self._safe_query_all(page, selector)
            if cards:
                break

        if not cards:
            self.log(
                "  ⚠️  No job cards found with known selectors — layout may have changed"
            )
            return []

        for card in cards[: self._max_jobs]:
            try:
                job = self._parse_card(card, page, domain)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.log_error("Failed to parse a job card", exc)

        return jobs

    def _parse_card(self, card, page: Page, domain: str) -> Optional[Job]:
        """
        Parse a single job card element into a Job object.

        JobStreet's DOM structure (as of 2024–2025):
          [data-automation="jobListing"]
            h3 [data-automation="job-title"] or h1
            a[data-automation="job-title"] — the link
            [data-automation="jobCompany"] or span[class*="company"]
            [data-automation="jobLocation"] or span[class*="location"]
            [data-automation="jobDate"] or span[class*="date"]
        """
        # ── Title & URL ───────────────────────────────────────────────────────
        title = ""
        url = ""

        title_selectors = [
            '[data-automation="job-title"]',
            "h3 a",
            "h1 a",
            'a[class*="job-title"]',
            'a[class*="jobTitle"]',
        ]
        for sel in title_selectors:
            try:
                el = card.query_selector(sel)
                if el:
                    title = (el.inner_text() or "").strip()
                    href = el.get_attribute("href") or ""
                    if href:
                        url = (
                            href
                            if href.startswith("http")
                            else f"https://{domain}{href}"
                        )
                    break
            except Exception:
                continue

        if not title:
            return None

        # ── Company ───────────────────────────────────────────────────────────
        company = ""
        company_selectors = [
            '[data-automation="jobCompany"]',
            '[class*="company"]',
            '[class*="Company"]',
            'span[class*="advertiser"]',
        ]
        for sel in company_selectors:
            company = self._safe_inner_text(card, sel)
            if company:
                break

        if not company:
            company = "Unknown Company"

        # ── Location ──────────────────────────────────────────────────────────
        location = ""
        location_selectors = [
            '[data-automation="jobLocation"]',
            '[class*="location"]',
            '[class*="Location"]',
            '[data-automation="job-location"]',
        ]
        for sel in location_selectors:
            location = self._safe_inner_text(card, sel)
            if location:
                break

        # ── Posted date ───────────────────────────────────────────────────────
        raw_date = ""
        date_selectors = [
            '[data-automation="jobDate"]',
            '[data-automation="job-posted"]',
            '[class*="date"]',
            '[class*="Date"]',
            "time",
        ]
        for sel in date_selectors:
            try:
                el = card.query_selector(sel)
                if el:
                    # Prefer datetime attribute for accuracy
                    dt_attr = el.get_attribute("datetime") or el.get_attribute("title")
                    raw_date = dt_attr or (el.inner_text() or "").strip()
                    if raw_date:
                        break
            except Exception:
                continue

        posted_at = parse_posted_date(raw_date)

        # ── Location type (from card text) ────────────────────────────────────
        card_text = ""
        try:
            card_text = card.inner_text() or ""
        except Exception:
            pass

        location_type = detect_location_type(title, card_text, location)

        # ── Job description (fetched from detail page for top cards) ──────────
        description = self._extract_card_snippet(card)

        # ── Easy Apply detection ──────────────────────────────────────────────
        easy_apply = self._detect_easy_apply(card)

        # ── Build Job object ──────────────────────────────────────────────────
        job_id = make_job_id(title, company, location)

        # If no direct URL from card, build one from domain + job ID in URL if present
        if not url and job_id:
            url = f"https://{domain}/job/{job_id}"

        return Job(
            id=job_id,
            title=title,
            company=company,
            location=location,
            location_type=location_type,
            source=self.source_name,
            url=url or f"https://{domain}",
            description=description,
            posted_at=posted_at,
            easy_apply=easy_apply,
        )

    def _extract_card_snippet(self, card) -> str:
        """
        Extract a short description snippet from the card if visible.
        JobStreet sometimes shows 1–2 bullet points on the card.
        """
        snippet_selectors = [
            '[data-automation="jobShortDescription"]',
            '[class*="snippet"]',
            '[class*="Snippet"]',
            '[class*="description"]',
            'ul[class*="bullet"]',
        ]
        for sel in snippet_selectors:
            text = self._safe_inner_text(card, sel)
            if text:
                return text[:2000]  # cap length
        return ""

    def _detect_easy_apply(self, card) -> bool:
        """Detect if JobStreet's 'Quick Apply' feature is available on this card."""
        try:
            card_html = card.inner_html() or ""
            card_lower = card_html.lower()
            return any(
                phrase in card_lower
                for phrase in ("quick apply", "easy apply", "apply now", "1-click")
            )
        except Exception:
            return False

    # ─── URL builder ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_search_url(domain: str, title: str, location: str) -> str:
        """
        Build a JobStreet search URL.

        Examples:
          https://www.jobstreet.com.my/jobs?keywords=software+engineer&where=Selangor
          https://www.jobstreet.co.id/jobs?keywords=product+manager&where=Jakarta
        """
        # Strip country suffix from location for the 'where' param
        where = re.sub(
            r",?\s*(malaysia|indonesia)$", "", location, flags=re.IGNORECASE
        ).strip()
        return (
            f"https://{domain}/jobs"
            f"?keywords={quote_plus(title)}"
            f"&where={quote_plus(where)}"
            f"&sortmode=ListedDate"  # sort by newest first
        )

    @staticmethod
    def _resolve_domain(location: str) -> Optional[str]:
        """Return the domain key ('malaysia' or 'indonesia') for a location string."""
        location_lower = location.lower().strip()
        # Direct mapping
        if location_lower in _LOCATION_DOMAIN_MAP:
            return _LOCATION_DOMAIN_MAP[location_lower]
        # Partial match
        if "malaysia" in location_lower:
            return "malaysia"
        if "indonesia" in location_lower:
            return "indonesia"
        return None
