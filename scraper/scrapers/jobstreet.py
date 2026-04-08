from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus

from apis.embedded_payloads import seek_jobs_from_html
from apis.http_fetch import fetch_html
from core.date_parser import parse_posted_date
from core.deduplicator import make_job_id
from core.models import Job, LocationType
from ranking.job_parser import detect_location_type
from scrapers.base import BaseScraper

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ─── JobStreet domain config ──────────────────────────────────────────────────

# SEEK hosts the Jobstreet product on regional subdomains. The legacy
# www.jobstreet.com.* hosts often serve a thin shell; listings hydrate on
# my.jobstreet.com (MY) and id.jobstreet.com (ID).
_DOMAINS: dict[str, str] = {
    "malaysia": "my.jobstreet.com",
    "indonesia": "id.jobstreet.com",
}

# Wait for any of these before parsing (layout A/B tests change often).
_JOB_LIST_SELECTORS = (
    '[data-automation="jobListing"], '
    '[data-automation="job-card"], '
    '[data-automation="normalJob"], '
    'article[data-job-id], '
    '[data-testid="job-card"], '
    'a[href*="/job/"]'
)

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
    Scrapes job listings from JobStreet Malaysia and Indonesia (SEEK-hosted).

    Primary method: HTTP GET of search URLs and parse ``window.SEEK_REDUX_DATA``
    from the HTML (first page, and page 2 when useful).

    Fallback: Playwright when SSR payload is missing or blocked.

    JobStreet is part of the SEEK group and is the dominant job board
    in Malaysia and Indonesia — high signal-to-noise for local roles.
    """

    source_name = "jobstreet"

    def scrape(self) -> list[Job]:
        self.log("Starting JobStreet scrape …")

        jobs = self._scrape_via_http()
        if jobs:
            self.log(
                f"HTTP/SSR path collected {len(jobs)} unique jobs (no browser)."
            )
            return jobs[: self._max_jobs]

        if not PLAYWRIGHT_AVAILABLE:
            self.log_error(
                "Playwright not installed — pip install playwright && playwright install chromium"
            )
            return []

        jobs = []

        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(
                **self._get_playwright_launch_options()
            )
            context: BrowserContext = browser.new_context(
                **self._get_browser_context_options()
            )
            page: Page = context.new_page()

            # Do not block images — SEEK/Jobstreet cards can depend on media/lazy paint.
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in ("font",)
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

    def _scrape_via_http(self) -> list[Job]:
        """Collect jobs from SEEK_REDUX_DATA embedded in search HTML."""
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for title in self.titles:
            for location in self.all_locations:
                domain_key = self._resolve_domain(location)
                if not domain_key:
                    continue
                domain = _DOMAINS[domain_key]

                for page_url in (
                    self._build_search_url(domain, title, location),
                    self._build_search_url(domain, title, location) + "&page=2",
                ):
                    if len(jobs) >= self._max_jobs:
                        break
                    self.log(f"[HTTP] GET …{page_url[-60:]}")
                    html = fetch_html(page_url)
                    self._delay()
                    if not html:
                        continue
                    items = seek_jobs_from_html(html)
                    for item in items:
                        if len(jobs) >= self._max_jobs:
                            break
                        job = self._job_from_seek_redux_item(item, domain)
                        if job and job.id not in seen_ids:
                            seen_ids.add(job.id)
                            jobs.append(job)
                    if not items:
                        break

            if len(jobs) >= self._max_jobs:
                break

        return jobs

    # ─── Search page scraper ──────────────────────────────────────────────────

    def _scrape_search(
        self,
        page: "Page",
        title: str,
        location: str,
        domain: str,
    ) -> list[Job]:
        """Navigate to a JobStreet search results page and extract job listings."""
        url = self._build_search_url(domain, title, location)
        self.log(f"Navigating → {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            self.log_error(f"Navigation failed for {url}", exc)
            return []

        # Listings hydrate from SEEK_REDUX_DATA; wait for jobs before DOM selectors.
        try:
            page.wait_for_function(
                """() => {
                    const d = window.SEEK_REDUX_DATA;
                    if (!d || !d.results) return false;
                    const inner = d.results.results;
                    if (inner && Array.isArray(inner.jobs) && inner.jobs.length > 0)
                        return true;
                    const j = d.results.jobs;
                    return Array.isArray(j) && j.length > 0;
                }""",
                timeout=55_000,
            )
        except Exception:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        page.wait_for_timeout(2_000)

        # Primary path: SEEK embeds the first results page in window.SEEK_REDUX_DATA
        # (inline script). This is reliable when the visible DOM uses hashed classes.
        jobs = self._extract_jobs_from_seek_redux(page, domain)
        if jobs:
            self._delay()
            return jobs

        # Fallback: wait for classic job-card selectors
        try:
            page.wait_for_selector(_JOB_LIST_SELECTORS, timeout=35_000)
        except Exception:
            self.log(
                f"No job cards found on {url} (page may be empty, blocked, or layout changed)"
            )
            return []

        self._delay()

        jobs = self._extract_jobs_from_page(page, domain, title, location)

        # Attempt to get page 2 for popular titles
        if len(jobs) < 20:
            return jobs

        try:
            page2_url = url + "&page=2"
            page.goto(page2_url, wait_until="load", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                pass
            page.wait_for_timeout(2_000)
            page2_jobs = self._extract_jobs_from_seek_redux(page, domain)
            if not page2_jobs:
                try:
                    page.wait_for_selector(_JOB_LIST_SELECTORS, timeout=15_000)
                except Exception:
                    pass
                page2_jobs = self._extract_jobs_from_page(
                    page, domain, title, location
                )
            self._delay()
            jobs.extend(page2_jobs)
        except Exception:
            pass  # Page 2 is a bonus — don't fail if unavailable

        return jobs

    def _extract_jobs_from_seek_redux(
        self,
        page: "Page",
        domain: str,
    ) -> list[Job]:
        """
        Read the first page of results from SEEK's SSR payload (window.SEEK_REDUX_DATA).
        The visible listing UI often uses unstable hashed class names; this object is stable.
        """
        try:
            raw = page.evaluate(
                """() => {
                    const d = window.SEEK_REDUX_DATA;
                    if (!d || !d.results) return [];
                    const inner = d.results.results;
                    if (inner && Array.isArray(inner.jobs)) return inner.jobs;
                    if (Array.isArray(d.results.jobs)) return d.results.jobs;
                    return [];
                }"""
            )
        except Exception:
            return []

        if not raw:
            return []

        jobs: list[Job] = []
        for item in raw[: self._max_jobs]:
            job = self._job_from_seek_redux_item(item, domain)
            if job:
                jobs.append(job)
        return jobs

    def _job_from_seek_redux_item(
        self,
        item: object,
        domain: str,
    ) -> Optional[Job]:
        if not isinstance(item, dict):
            return None

        title = (item.get("title") or "").strip()
        if not title:
            return None

        jid = str(item.get("id") or "").strip()
        url = f"https://{domain}/job/{jid}" if jid else f"https://{domain}"

        advertiser = item.get("advertiser") if isinstance(item.get("advertiser"), dict) else {}
        company = (
            (item.get("companyName") or "").strip()
            or (advertiser.get("description") or "").strip()
            or "Unknown Company"
        )

        location = ""
        locs = item.get("locations")
        if isinstance(locs, list) and locs and isinstance(locs[0], dict):
            location = (locs[0].get("label") or "").strip()

        desc_parts: list[str] = []
        teaser = item.get("teaser")
        if isinstance(teaser, str) and teaser.strip():
            desc_parts.append(teaser.strip())
        bullets = item.get("bulletPoints")
        if isinstance(bullets, list):
            for b in bullets:
                if isinstance(b, str) and b.strip():
                    desc_parts.append(b.strip())
        description = "\n".join(desc_parts)[:5000] if desc_parts else ""

        raw_date = item.get("listingDate") or item.get("listingDateDisplay") or ""
        posted_at = parse_posted_date(str(raw_date)) if raw_date else None

        wa = item.get("workArrangements") if isinstance(item.get("workArrangements"), dict) else {}
        wt = item.get("workTypes") if isinstance(item.get("workTypes"), list) else []
        wt_text = " ".join(str(x) for x in wt if x)
        arrangement = (wa.get("displayText") or "").strip()
        card_blob = f"{title} {wt_text} {arrangement} {location}"

        location_type = detect_location_type(
            title,
            f"{card_blob}\n{description}",
            location,
        )

        job_id = make_job_id(title, company, location)

        return Job(
            id=job_id,
            title=title,
            company=company,
            location=location or None,
            location_type=location_type,
            source=self.source_name,
            url=url,
            description=description or None,
            posted_at=posted_at,
            easy_apply=False,
        )

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
            '[data-automation="normalJob"]',
            "article[data-job-id]",
            '[data-testid="job-card"]',
            'div[class*="JobCard"]',
            'div[class*="job-card"]',
            "li[data-job-id]",
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

        # Fallback: any job detail link inside the card (SEEK / Jobstreet paths)
        if not url:
            try:
                link = card.query_selector('a[href*="/job/"]')
                if not link:
                    link = card.query_selector(f'a[href*="{domain}"][href*="/job"]')
                if link:
                    href = link.get_attribute("href") or ""
                    if href:
                        url = (
                            href
                            if href.startswith("http")
                            else f"https://{domain}{href}"
                        )
                    if not title:
                        title = (link.inner_text() or link.get_attribute("aria-label") or "").strip()
            except Exception:
                pass

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
        # "Malaysia" / "Indonesia" alone become '' after the strip — SEEK needs a region.
        if not where:
            if "id.jobstreet" in domain:
                where = "Indonesia"
            else:
                where = "Malaysia"
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
