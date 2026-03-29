from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus

from core.date_parser import parse_posted_date
from core.deduplicator import make_job_id
from core.models import Job, LocationType
from ranking.job_parser import detect_location_type
from scrapers.base import BaseScraper

try:
    from playwright.sync_api import Page, sync_playwright
    from playwright.sync_api import TimeoutError as PWTimeout

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ─── Country / domain config ──────────────────────────────────────────────────

_COUNTRY_CONFIG: dict[str, dict] = {
    "Malaysia": {
        "domain": "malaysia.indeed.com",
        "base_url": "https://malaysia.indeed.com/jobs",
        "location_default": "Malaysia",
    },
    "Indonesia": {
        "domain": "id.indeed.com",
        "base_url": "https://id.indeed.com/lowongan",
        "location_default": "Indonesia",
    },
}

_LOCATION_COUNTRY_MAP: dict[str, str] = {
    "selangor, malaysia": "Malaysia",
    "kuala lumpur, malaysia": "Malaysia",
    "petaling jaya, malaysia": "Malaysia",
    "malaysia": "Malaysia",
    "jakarta, indonesia": "Indonesia",
    "indonesia": "Indonesia",
}

# ─── CSS Selectors ────────────────────────────────────────────────────────────
# Indeed's DOM structure as of mid-2025.
# Indeed uses data-jk attributes for job IDs and frequently A/B tests layouts.

_SEL = {
    # Search results page
    "job_cards": "div.job_seen_beacon, li.css-1ac2h1w, div[data-testid='jobCard'], div.tapItem",
    "card_title": "h2.jobTitle a, h2[data-testid='jobTitle'] a, a.jcs-JobTitle, a[id^='job_']",
    "card_company": "span[data-testid='company-name'], span.css-1h7lukg, div.company_location span",
    "card_location": "div[data-testid='text-location'], span.css-bnj0lk, div.companyLocation",
    "card_posted": "span[data-testid='myJobsStateDate'], span.date, span[class*='date']",
    "card_salary": "div[data-testid='attribute_snippet_testid'], span[class*='salary']",
    # Job detail page / side panel
    "detail_title": "h2.jobsearch-JobInfoHeader-title, h1.jobTitle, h1[class*='JobTitle']",
    "detail_company": "div[data-testid='inlineHeader-companyName'] a, div.jobsearch-CompanyInfoContainer a",
    "detail_location": "div[data-testid='job-location'], div[class*='Location']",
    "detail_description": "div#jobDescriptionText, div[id='jobDescriptionText'], div.jobsearch-jobDescriptionText",
    "detail_posted": "span[data-testid='jobsearch-JobMetadataFooter'] span, p.jobsearch-HiringInsights-entry--update",
    "detail_type": "div[data-testid='jobDetailsSection-jobtype'] span, div[class*='JobType'] span",
    # Pagination
    "next_button": "a[data-testid='pagination-page-next'], a[aria-label='Next Page']",
    # Cookie / consent popup
    "cookie_btn": "button#onetrust-accept-btn-handler, button[id*='accept'], button[class*='accept-cookies']",
    # Captcha / robot check
    "captcha_heading": "h1#captcha_title, div.g-recaptcha, div[class*='captcha']",
}


class IndeedScraper(BaseScraper):
    """
    Scrapes job listings from Indeed Malaysia (malaysia.indeed.com)
    and Indeed Indonesia (id.indeed.com) using Playwright.

    Strategy:
        1. Navigate to the Indeed job search results page for each title × country.
        2. Extract job cards from the results list.
        3. For each card, click it to load the side-panel detail and capture
           the full job description.
        4. Fall back to navigating directly to the job detail URL if the
           side panel is not available.

    Note on Indeed bot detection:
        Indeed is moderately aggressive about blocking scrapers.  This scraper
        uses randomised delays, a realistic user-agent, and avoids loading
        images/media to stay under the radar.  If you encounter CAPTCHAs,
        increase the delay values in config.yaml.
    """

    source_name = "indeed"

    def scrape(self) -> list[Job]:
        if not PLAYWRIGHT_AVAILABLE:
            self.log_error(
                "Playwright not installed — "
                "run: pip install playwright && playwright install chromium"
            )
            return []

        self.log("Starting Indeed scrape …")
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**self._get_playwright_launch_options())
            context = browser.new_context(**self._get_browser_context_options())
            page = context.new_page()

            # Block resource types that are unnecessary and slow down scraping
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type
                    in ("image", "media", "font", "stylesheet")
                    else route.continue_()
                ),
            )

            for title in self.titles:
                if len(jobs) >= self._max_jobs:
                    break

                for country_name, cfg in _COUNTRY_CONFIG.items():
                    if not self._should_scrape_country(country_name):
                        continue

                    if len(jobs) >= self._max_jobs:
                        break

                    self.log(f"Searching '{title}' on Indeed {country_name} …")

                    try:
                        new_jobs = self._scrape_search(
                            page=page,
                            title=title,
                            country_name=country_name,
                            cfg=cfg,
                        )
                        for job in new_jobs:
                            if job.id not in seen_ids:
                                seen_ids.add(job.id)
                                jobs.append(job)

                        self.log_found(len(new_jobs), title, country_name)
                    except Exception as exc:
                        self.log_error(
                            f"Search error for '{title}' / {country_name}", exc
                        )

                    self._delay()

            context.close()
            browser.close()

        self.log(f"Done — {len(jobs)} unique Indeed jobs collected.")
        return jobs

    # ─── Search page ─────────────────────────────────────────────────────────

    def _scrape_search(
        self,
        page: "Page",
        title: str,
        country_name: str,
        cfg: dict,
        max_pages: int = 2,
    ) -> list[Job]:
        jobs: list[Job] = []
        location = cfg["location_default"]

        for page_num in range(max_pages):
            url = self._build_search_url(cfg, title, location, page_num)
            self.log(f"  Page {page_num + 1}: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                self._dismiss_popups(page)
            except Exception as exc:
                self.log_error(f"Navigation failed: {url}", exc)
                break

            # Check for CAPTCHA
            if self._is_captcha_page(page):
                self.log_error(
                    "CAPTCHA detected — Indeed is blocking this request. "
                    "Try increasing delay_between_requests in config.yaml."
                )
                break

            # Wait for job cards
            try:
                page.wait_for_selector(_SEL["job_cards"], timeout=12_000)
            except PWTimeout:
                self.log(f"  No job cards found on page {page_num + 1} — stopping.")
                break

            self._delay(extra_min=0.5, extra_max=1.5)

            cards = self._safe_query_all(page, _SEL["job_cards"])
            self.log(f"  Found {len(cards)} job cards")

            if not cards:
                break

            page_jobs = self._extract_cards(page, cards, cfg, country_name)
            jobs.extend(page_jobs)

            # Check if there is a next page
            if not self._has_next_page(page):
                break

            self._delay()

        return jobs

    # ─── Card extraction ──────────────────────────────────────────────────────

    def _extract_cards(
        self,
        page: "Page",
        cards: list,
        cfg: dict,
        country_name: str,
    ) -> list[Job]:
        jobs: list[Job] = []

        for card in cards[: self._max_jobs]:
            try:
                job = self._parse_card(page, card, cfg, country_name)
                if job:
                    jobs.append(job)
                    self._delay(extra_min=0.3, extra_max=0.8)
            except Exception as exc:
                self.log_error("Card parse error", exc)

        return jobs

    def _parse_card(
        self,
        page: "Page",
        card,
        cfg: dict,
        country_name: str,
    ) -> Optional[Job]:
        """
        Parse a single Indeed job card.

        Indeed renders job details in a side panel when a card is clicked.
        We attempt to click the card title and read the panel; if that fails,
        we navigate directly to the job URL.
        """
        # ── Title & job-key (Indeed's internal ID) ────────────────────────────
        title = ""
        job_url = ""
        job_key = ""

        title_selectors = _SEL["card_title"].split(", ")
        for sel in title_selectors:
            try:
                el = card.query_selector(sel)
                if el:
                    title = (el.inner_text() or "").strip()
                    href = el.get_attribute("href") or ""
                    if href:
                        job_url = (
                            href
                            if href.startswith("http")
                            else f"https://{cfg['domain']}{href}"
                        )
                    # Extract jk= param for the canonical job URL
                    jk_match = re.search(r"jk=([a-f0-9]+)", href)
                    if jk_match:
                        job_key = jk_match.group(1)
                    break
            except Exception:
                continue

        if not title:
            return None

        # ── Company ───────────────────────────────────────────────────────────
        company = ""
        for sel in _SEL["card_company"].split(", "):
            company = self._safe_inner_text(card, sel)
            if company:
                break
        if not company:
            company = "Unknown Company"

        # ── Location (from card) ──────────────────────────────────────────────
        location = ""
        for sel in _SEL["card_location"].split(", "):
            location = self._safe_inner_text(card, sel)
            if location:
                break

        # ── Posted date (from card) ───────────────────────────────────────────
        raw_posted = ""
        for sel in _SEL["card_posted"].split(", "):
            raw_posted = self._safe_inner_text(card, sel)
            if raw_posted:
                break

        # ── Description — try side panel first, then detail page ──────────────
        description, detail_location, detail_type, detail_posted = (
            self._get_job_description(page, card, job_url, cfg)
        )

        # Merge detail fields
        location = location or detail_location or country_name
        raw_posted = raw_posted or detail_posted

        # ── Location type ─────────────────────────────────────────────────────
        card_text = ""
        try:
            card_text = card.inner_text() or ""
        except Exception:
            pass

        location_type = _parse_work_type(detail_type) or detect_location_type(
            title, description or "", card_text + " " + location
        )

        # ── Canonical job URL ─────────────────────────────────────────────────
        if job_key and not job_url:
            job_url = f"https://{cfg['domain']}/viewjob?jk={job_key}"
        elif not job_url:
            job_url = f"https://{cfg['domain']}/jobs"

        return Job(
            id=make_job_id(title, company, location),
            title=title,
            company=company,
            location=location.strip() if location else None,
            location_type=location_type,
            source=self.source_name,
            url=job_url,
            description=description,
            posted_at=parse_posted_date(raw_posted),
            easy_apply=False,  # Indeed redirects to employer sites for most postings
        )

    # ─── Job description extraction ───────────────────────────────────────────

    def _get_job_description(
        self,
        page: "Page",
        card,
        job_url: str,
        cfg: dict,
    ) -> tuple[str, str, str, str]:
        """
        Try two strategies to get the full job description:
          1. Click the card to open Indeed's right-hand side panel (fast, no navigation).
          2. Navigate directly to the job detail URL (slower but more reliable).

        Returns: (description, location, work_type, posted_date)
        """
        description = location = work_type = posted_date = ""

        # ── Strategy 1: side panel ────────────────────────────────────────────
        try:
            title_el = card.query_selector("h2.jobTitle a, a.jcs-JobTitle")
            if title_el:
                title_el.click()
                # Indeed loads the detail panel in a div on the right side
                page.wait_for_selector(_SEL["detail_description"], timeout=6_000)
                description = self._safe_inner_text(page, _SEL["detail_description"])
                location = self._safe_inner_text(page, _SEL["detail_location"])
                work_type = self._safe_inner_text(page, _SEL["detail_type"])
                posted_date = self._safe_inner_text(page, _SEL["detail_posted"])

                if description:
                    return description, location, work_type, posted_date
        except Exception:
            pass

        # ── Strategy 2: direct navigation ────────────────────────────────────
        if not job_url:
            return description, location, work_type, posted_date

        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=20_000)
            self._dismiss_popups(page)

            try:
                page.wait_for_selector(_SEL["detail_description"], timeout=8_000)
            except PWTimeout:
                pass

            description = self._safe_inner_text(page, _SEL["detail_description"])
            location = self._safe_inner_text(page, _SEL["detail_location"]) or location
            work_type = self._safe_inner_text(page, _SEL["detail_type"])
            posted_date = self._safe_inner_text(page, _SEL["detail_posted"])

        except Exception as exc:
            self.log_error(f"Detail page error ({job_url[:60]}…)", exc)

        return description, location, work_type, posted_date

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _dismiss_popups(self, page: "Page") -> None:
        """Dismiss cookie consent banners and other modal overlays."""
        dismiss_selectors = [
            "button#onetrust-accept-btn-handler",
            "button[id*='accept']",
            "button[class*='accept-cookies']",
            "button[aria-label='Close']",
            "button[data-gnav-element-name='CloseButton']",
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.4)
            except Exception:
                pass

    def _is_captcha_page(self, page: "Page") -> bool:
        """Return True if the current page appears to be a CAPTCHA challenge."""
        try:
            el = page.query_selector(_SEL["captcha_heading"])
            return bool(el)
        except Exception:
            return False

    def _has_next_page(self, page: "Page") -> bool:
        """Return True if a 'Next page' pagination link is present and clickable."""
        try:
            btn = page.query_selector(_SEL["next_button"])
            return bool(btn and btn.is_visible())
        except Exception:
            return False

    def _should_scrape_country(self, country_name: str) -> bool:
        """
        Only scrape a country if at least one configured location references it.
        """
        all_locs = " ".join(self.all_locations).lower()
        return country_name.lower() in all_locs

    @staticmethod
    def _build_search_url(cfg: dict, title: str, location: str, page_num: int) -> str:
        """
        Build an Indeed search URL.

        Examples:
          https://malaysia.indeed.com/jobs?q=software+engineer&l=Selangor&sort=date&start=0
          https://id.indeed.com/lowongan?q=product+manager&l=Jakarta&sort=date&start=10
        """
        params = f"q={quote_plus(title)}&l={quote_plus(location)}&sort=date&start={page_num * 10}"
        return f"{cfg['base_url']}?{params}"


# ─── Work-type parser ─────────────────────────────────────────────────────────


def _parse_work_type(raw: str) -> Optional[LocationType]:
    """Parse Indeed's job-type label into a LocationType enum value."""
    if not raw:
        return None
    text = raw.lower()
    if "remote" in text:
        return LocationType.REMOTE
    if "hybrid" in text:
        return LocationType.HYBRID
    if any(w in text for w in ("on-site", "onsite", "office")):
        return LocationType.ON_SITE
    return None
