from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from typing import Optional

from core.date_parser import parse_posted_date
from core.deduplicator import make_job_id
from core.models import Job, LocationType
from ranking.job_parser import detect_location_type
from scrapers.base import BaseScraper

# ─── linkedin-api (tomquirk) ──────────────────────────────────────────────────
try:
    from linkedin_api import Linkedin as LinkedinAPI

    LINKEDIN_API_AVAILABLE = True
except ImportError:
    LINKEDIN_API_AVAILABLE = False

# ─── Playwright ───────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class LinkedInScraper(BaseScraper):
    """
    LinkedIn job scraper.

    Primary method  : linkedin-api (tomquirk) — uses LinkedIn's internal mobile
                      API endpoints via your account credentials.  No browser
                      required; fast and comprehensive.

    Fallback method : Playwright — navigates LinkedIn Jobs in a real browser
                      using your session cookies stored as GitHub Secrets.
                      Used automatically when the API is rate-limited or
                      credentials are unavailable.

    Environment variables / GitHub Secrets required:
        LINKEDIN_EMAIL      – your LinkedIn login email
        LINKEDIN_PASSWORD   – your LinkedIn password
        LINKEDIN_COOKIES    – (optional) JSON-serialised Playwright cookies for
                              the fallback method (export from a logged-in session)

    Rate-limiting protection:
        • Random 3–8 s delay between API calls
        • Maximum 50 jobs per scrape run (configurable)
        • Searches are spread across title × location pairs rather than hammering
          a single large query
    """

    source_name = "linkedin"

    # ── Public entry point ────────────────────────────────────────────────────

    def scrape(self) -> list[Job]:
        self.log("Starting scrape …")

        if LINKEDIN_API_AVAILABLE and self._has_api_credentials():
            jobs = self._scrape_via_api()
            if jobs:
                return jobs
            self.log("API returned 0 results — falling back to Playwright")

        if PLAYWRIGHT_AVAILABLE:
            return self._scrape_via_playwright()

        self.log_error(
            "Neither linkedin-api nor Playwright is available. "
            "Run: pip install linkedin-api playwright && playwright install chromium"
        )
        return []

    # ─── linkedin-api method ──────────────────────────────────────────────────

    def _has_api_credentials(self) -> bool:
        return bool(
            os.environ.get("LINKEDIN_EMAIL") and os.environ.get("LINKEDIN_PASSWORD")
        )

    def _scrape_via_api(self) -> list[Job]:
        email = os.environ["LINKEDIN_EMAIL"]
        password = os.environ["LINKEDIN_PASSWORD"]

        try:
            self.log("Authenticating with linkedin-api …")
            api = LinkedinAPI(
                email,
                password,
                authenticate=True,
                refresh_cookies=True,
                debug=False,
            )
        except Exception as exc:
            self.log_error("Authentication failed", exc)
            return []

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for title in self.titles:
            if len(jobs) >= self._max_jobs:
                break

            # Search both on-site and remote locations
            for location in self.all_locations:
                if len(jobs) >= self._max_jobs:
                    break

                self.log(f"Searching: '{title}' in '{location}' …")
                try:
                    results = api.search_jobs(
                        keywords=title,
                        location_name=location,
                        listed_at=24 * 60 * 60 * 30,  # last 30 days (in seconds)
                        limit=min(20, self._max_jobs - len(jobs)),
                    )
                except Exception as exc:
                    self.log_error(f"Search failed for '{title}' / '{location}'", exc)
                    self._delay()
                    continue

                self.log_found(len(results), title, location)

                for result in results:
                    if len(jobs) >= self._max_jobs:
                        break

                    job = self._parse_api_result(api, result)
                    if job and job.id not in seen_ids:
                        jobs.append(job)
                        seen_ids.add(job.id)

                    self._delay()

        self.log(f"API scrape complete — {len(jobs)} unique jobs collected")
        return jobs

    def _parse_api_result(self, api: "LinkedinAPI", result: dict) -> Optional[Job]:
        try:
            # ── Extract job ID from URN ───────────────────────────────────────
            entity_urn: str = result.get("entityUrn", "")
            job_id_li = entity_urn.split(":")[-1]

            if not job_id_li:
                return None

            # ── Fetch full job details ────────────────────────────────────────
            try:
                details: dict = api.get_job(job_id_li)
            except Exception:
                details = result  # fall back to search result data

            # ── Title ─────────────────────────────────────────────────────────
            title: str = (details.get("title") or result.get("title") or "").strip()

            if not title:
                return None

            # ── Company ───────────────────────────────────────────────────────
            company = self._extract_company(details, result)

            # ── Location ──────────────────────────────────────────────────────
            location: str = (
                details.get("formattedLocation")
                or result.get("formattedLocation")
                or result.get("secondaryDescription", {}).get("text", "")
                or ""
            ).strip()

            # ── Description ───────────────────────────────────────────────────
            desc_obj = details.get("description", {})
            description: str = ""
            if isinstance(desc_obj, dict):
                description = desc_obj.get("text", "")
            elif isinstance(desc_obj, str):
                description = desc_obj

            # ── URL ───────────────────────────────────────────────────────────
            url = f"https://www.linkedin.com/jobs/view/{job_id_li}"

            # ── Posted date ───────────────────────────────────────────────────
            listed_at_ms = details.get("listedAt") or result.get("listedAt")
            posted_at: Optional[datetime] = None
            if listed_at_ms:
                try:
                    posted_at = datetime.fromtimestamp(
                        int(listed_at_ms) / 1000, tz=timezone.utc
                    )
                except (ValueError, OSError):
                    pass

            # ── Easy Apply ────────────────────────────────────────────────────
            apply_method = details.get("applyMethod", {})
            # EasyApply uses com.linkedin.voyager.jobs.ComplexOnsiteApply
            easy_apply = "OffsiteApply" not in str(apply_method)

            # ── Location type ─────────────────────────────────────────────────
            work_remote: bool = bool(details.get("workRemoteAllowed", False))
            if work_remote:
                location_type: Optional[LocationType] = LocationType.REMOTE
            else:
                location_type = detect_location_type(title, description, location)
                if location_type is None:
                    location_type = LocationType.ON_SITE  # LinkedIn default

            return Job(
                id=make_job_id(title, company, location),
                title=title,
                company=company,
                location=location,
                location_type=location_type,
                source=self.source_name,
                url=url,
                description=description,
                posted_at=posted_at,
                easy_apply=easy_apply,
            )

        except Exception as exc:
            self.log_error(f"Failed to parse API result: {exc}")
            return None

    def _extract_company(self, details: dict, fallback: dict) -> str:
        """Dig through the nested LinkedIn API company structure."""
        # Path 1: companyDetails → WebCompactJobPostingCompany → companyResolutionResult
        company_details = details.get("companyDetails", {})
        for key, val in company_details.items():
            if isinstance(val, dict):
                resolution = val.get("companyResolutionResult", {})
                if isinstance(resolution, dict):
                    name = resolution.get("name", "")
                    if name:
                        return name.strip()

        # Path 2: primaryDescription (from search result)
        primary = fallback.get("primaryDescription", {})
        if isinstance(primary, dict):
            name = primary.get("text", "")
            if name:
                return name.strip()

        # Path 3: company name directly
        return str(
            details.get("companyName", "")
            or fallback.get("companyName", "")
            or "Unknown"
        ).strip()

    # ─── Playwright fallback method ───────────────────────────────────────────

    def _scrape_via_playwright(self) -> list[Job]:
        """
        Scrape LinkedIn Jobs using a real Chromium browser.

        Uses LINKEDIN_COOKIES (JSON array of cookie dicts) if available to
        skip the login page entirely.  Otherwise falls back to
        LINKEDIN_EMAIL + LINKEDIN_PASSWORD to log in programmatically.
        """
        self.log("Starting Playwright fallback …")
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**self._get_playwright_launch_options())
            context = browser.new_context(**self._get_browser_context_options())

            # ── Inject saved cookies to skip login ────────────────────────────
            cookies_json = os.environ.get("LINKEDIN_COOKIES", "")
            if cookies_json:
                try:
                    import json

                    context.add_cookies(json.loads(cookies_json))
                    self.log("Session cookies injected ✓")
                except Exception as exc:
                    self.log_error("Failed to inject cookies", exc)

            page = context.new_page()

            # ── Log in if no cookies ──────────────────────────────────────────
            if not cookies_json and self._has_api_credentials():
                self._playwright_login(page)

            # ── Scrape each title × location combination ──────────────────────
            for title in self.titles:
                if len(jobs) >= self._max_jobs:
                    break

                for location in self.all_locations:
                    if len(jobs) >= self._max_jobs:
                        break

                    new_jobs = self._playwright_search(page, title, location, seen_ids)
                    jobs.extend(new_jobs)
                    for j in new_jobs:
                        seen_ids.add(j.id)

                    self._delay()

            browser.close()

        self.log(f"Playwright scrape complete — {len(jobs)} unique jobs collected")
        return jobs

    def _playwright_login(self, page) -> None:
        """Perform a programmatic login via the LinkedIn sign-in page."""
        email = os.environ.get("LINKEDIN_EMAIL", "")
        password = os.environ.get("LINKEDIN_PASSWORD", "")
        if not email or not password:
            return

        self.log("Logging in via Playwright …")
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            page.fill("#username", email)
            page.fill("#password", password)
            page.click('[data-litms-control-urn="login-submit"]')
            page.wait_for_url("**/feed/**", timeout=15_000)
            self.log("Playwright login successful ✓")
            self._delay(extra_min=1, extra_max=2)
        except Exception as exc:
            self.log_error("Playwright login failed", exc)

    def _playwright_search(
        self,
        page,
        title: str,
        location: str,
        seen_ids: set[str],
    ) -> list[Job]:
        """Navigate to LinkedIn job search results and extract job cards."""
        import urllib.parse

        query = urllib.parse.urlencode(
            {"keywords": title, "location": location, "f_TPR": "r2592000"}
        )
        url = f"https://www.linkedin.com/jobs/search/?{query}"

        self.log(f"Playwright searching: '{title}' in '{location}' …")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            self.log_error(f"Navigation failed for '{title}' / '{location}'", exc)
            return []

        # Scroll to load more results
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)

        # ── Collect job card links ─────────────────────────────────────────────
        card_selectors = [
            "a.job-card-list__title",
            "a.job-card-container__link",
            ".jobs-search__results-list li a",
            "a[href*='/jobs/view/']",
        ]

        job_links: list[str] = []
        for sel in card_selectors:
            elements = self._safe_query_all(page, sel)
            if elements:
                for el in elements:
                    href = el.get_attribute("href") or ""
                    if "/jobs/view/" in href and href not in job_links:
                        job_links.append(href.split("?")[0])
                break

        self.log_found(len(job_links), title, location)

        jobs: list[Job] = []
        for job_url in job_links[: self._max_jobs]:
            job = self._playwright_scrape_job(page, job_url)
            if job and job.id not in seen_ids:
                jobs.append(job)
            self._delay()

        return jobs

    def _playwright_scrape_job(self, page, job_url: str) -> Optional[Job]:
        """Navigate to a LinkedIn job detail page and extract all fields."""
        if not job_url.startswith("http"):
            job_url = "https://www.linkedin.com" + job_url

        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(1500)
        except Exception as exc:
            self.log_error(f"Could not load job page: {job_url}", exc)
            return None

        try:
            # Title
            title = (
                self._safe_inner_text(page, "h1.jobs-unified-top-card__job-title")
                or self._safe_inner_text(page, "h1.t-24")
                or self._safe_inner_text(page, "h1")
            )

            if not title:
                return None

            # Company
            company = (
                self._safe_inner_text(page, ".jobs-unified-top-card__company-name a")
                or self._safe_inner_text(page, ".jobs-unified-top-card__company-name")
                or self._safe_inner_text(page, "a.ember-view.t-black.t-normal")
            )

            # Location
            location = self._safe_inner_text(
                page, ".jobs-unified-top-card__bullet"
            ) or self._safe_inner_text(page, ".jobs-unified-top-card__workplace-type")

            # Description — click "Show more" if present
            try:
                show_more = page.query_selector(
                    "button.jobs-description__footer-button"
                )
                if show_more:
                    show_more.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass

            description = (
                self._safe_inner_text(page, ".jobs-description-content__text")
                or self._safe_inner_text(page, "#job-details")
                or self._safe_inner_text(page, ".jobs-description__container")
            )

            # Posted date
            posted_raw = self._safe_inner_text(
                page, ".jobs-unified-top-card__posted-date"
            ) or self._safe_inner_text(page, "span.tvm__text--low-emphasis")
            posted_at = parse_posted_date(posted_raw)

            # Easy apply
            easy_apply = bool(
                page.query_selector(".jobs-apply-button--top-card")
                or page.query_selector("button[aria-label*='Easy Apply']")
            )

            # Location type
            location_type = detect_location_type(title, description, location)

            return Job(
                id=make_job_id(title, company or "Unknown", location),
                title=title,
                company=company or "Unknown",
                location=location,
                location_type=location_type,
                source=self.source_name,
                url=job_url,
                description=description,
                posted_at=posted_at,
                easy_apply=easy_apply,
            )

        except Exception as exc:
            self.log_error(f"Failed to parse job page {job_url}", exc)
            return None
