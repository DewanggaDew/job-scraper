from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import quote_plus, urlencode

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


# ─── Kalibrr domain config ────────────────────────────────────────────────────
# Kalibrr operates primarily in Indonesia (kalibrr.id) and the Philippines.
# We target the Indonesian domain since that matches the configured locations.

# Kalibrr merged regional sites onto kalibrr.com; /job-board on .id redirects away
# from SSR job data. The Indonesian job search home is id-ID/home (see __NEXT_DATA__).
_BASE_URL = "https://www.kalibrr.com"
_SEARCH_PATH = "/id-ID/home"
_SEARCH_URL = f"{_BASE_URL}{_SEARCH_PATH}"

# ─── CSS Selectors ────────────────────────────────────────────────────────────
# Kalibrr uses a server-rendered + React-hydrated frontend.
# Selectors are listed with fallbacks in priority order.

_SEL = {
    # Search results page — job card containers
    "job_cards": [
        "div[data-kjs-job-card]",
        "li[data-kjs-job-list-item]",
        "a[data-kjs-job-link]",
        "div.k-card.k-job-posting-card",
        "div[class*='JobPostingCard']",
        "div[class*='job-card']",
        "div[class*='JobCard']",
        "article[class*='job']",
    ],
    # Inside a job card
    "card_title": [
        "h2[data-kjs-job-name]",
        "h2[class*='job-name']",
        "h2[class*='JobName']",
        "h3[class*='job-title']",
        "a[class*='job-name']",
        "h2",
        "h3",
    ],
    "card_company": [
        "span[data-kjs-company-name]",
        "span[class*='company-name']",
        "span[class*='CompanyName']",
        "a[class*='company']",
        "div[class*='company']",
    ],
    "card_location": [
        "span[data-kjs-location]",
        "span[class*='location']",
        "span[class*='Location']",
        "div[class*='location']",
        "li[class*='location']",
    ],
    "card_posted": [
        "time[data-kjs-posted]",
        "span[class*='posted']",
        "span[class*='date']",
        "time",
        "span[class*='time']",
    ],
    "card_link": [
        "a[data-kjs-job-link]",
        "a[href*='/job-board/']",
        "a[class*='job-name']",
        "h2 a",
        "h3 a",
    ],
    "card_type": [
        "span[data-kjs-work-setup]",
        "span[class*='work-setup']",
        "span[class*='WorkSetup']",
        "span[class*='remote']",
        "div[class*='arrangement']",
    ],
    # Job detail page
    "detail_title": [
        "h1[data-kjs-job-title]",
        "h1[class*='job-title']",
        "h1[class*='JobTitle']",
        "h1",
    ],
    "detail_company": [
        "a[data-kjs-company]",
        "span[class*='CompanyName']",
        "a[class*='company-link']",
        "h2[class*='company']",
    ],
    "detail_location": [
        "span[data-kjs-address]",
        "span[class*='address']",
        "span[class*='location']",
        "li[class*='location']",
    ],
    "detail_description": [
        "div[data-kjs-job-description]",
        "div[class*='job-description']",
        "div[class*='JobDescription']",
        "section[class*='description']",
        "div.k-description",
        "div[class*='Description']",
    ],
    "detail_posted": [
        "time[data-kjs-posted-at]",
        "span[class*='posted']",
        "time",
        "span[class*='date']",
    ],
    "detail_type": [
        "span[data-kjs-work-setup]",
        "span[class*='work-setup']",
        "li[class*='work-setup']",
        "span[class*='arrangement']",
    ],
    # Pagination
    "next_page": [
        "a[rel='next']",
        "a[aria-label='Next']",
        "li.next a",
        "a[class*='next']",
        "button[aria-label='Next page']",
    ],
    # Popups / modals to dismiss
    "modal_close": [
        "button[aria-label='Close']",
        "button[class*='close-modal']",
        "button[class*='CloseButton']",
        "span[class*='k-modal__close']",
        "div.k-modal button.k-button--secondary",
    ],
}


class KalibrrScraper(BaseScraper):
    """
    Scrapes job listings from Kalibrr Indonesia (kalibrr.id).

    Kalibrr is popular in Indonesia for technology, business, and creative
    roles — particularly strong for Jakarta-based positions.

    Uses Playwright to render the React-hydrated pages, extract job cards from
    the search results, and then visit each detail page for the full description.

    Search URL format:
        https://www.kalibrr.id/job-board?keyword=software+engineer&location=Jakarta
    """

    source_name = "kalibrr"

    def scrape(self) -> list[Job]:
        if not PLAYWRIGHT_AVAILABLE:
            self.log_error(
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            return []

        # Kalibrr is Indonesia-focused; skip if no Indonesian locations configured
        if not self._has_indonesian_locations():
            self.log("No Indonesian locations in config — skipping Kalibrr.")
            return []

        self.log("Starting Kalibrr scrape …")
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**self._get_playwright_launch_options())
            context = browser.new_context(**self._get_browser_context_options())
            page = context.new_page()

            # Block images and media to speed up scraping
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_()
                ),
            )

            for title in self.titles:
                if len(jobs) >= self._max_jobs:
                    break

                # Use Jakarta as the primary location for Kalibrr
                for location in self._get_indonesian_locations():
                    if len(jobs) >= self._max_jobs:
                        break

                    self.log(f"Searching '{title}' in '{location}' …")
                    try:
                        results = self._scrape_search(page, title, location, seen_ids)
                        self.log_found(len(results), title, location)

                        for job in results:
                            if job.id not in seen_ids:
                                seen_ids.add(job.id)
                                jobs.append(job)

                    except Exception as exc:
                        self.log_error(
                            f"Search failed for '{title}' / '{location}'", exc
                        )

                    self._delay()

            context.close()
            browser.close()

        self.log(f"✅  Total jobs collected: {len(jobs)}")
        return jobs

    # ─── Search page ──────────────────────────────────────────────────────────

    def _scrape_search(
        self,
        page: "Page",
        title: str,
        location: str,
        seen_ids: set[str],
        max_pages: int = 3,
    ) -> list[Job]:
        jobs: list[Job] = []
        current_page = 1

        while current_page <= max_pages and len(jobs) < self._max_jobs:
            url = self._build_search_url(title, location, page_num=current_page)
            self.log(f"  Page {current_page} → {url}")

            n_before = len(jobs)

            try:
                page.goto(url, wait_until="load", timeout=45_000)
            except Exception as exc:
                self.log_error(f"Navigation failed: {url}", exc)
                break

            self._dismiss_popups(page)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(2_000)

            # Primary: Next.js embeds jobs in #__NEXT_DATA__ (reliable vs hydrated cards).
            page_jobs = self._extract_jobs_from_next_data(page)
            if page_jobs:
                self.log(
                    f"  Found {len(page_jobs)} jobs from __NEXT_DATA__ "
                    f"(page {current_page})"
                )
                for job in page_jobs:
                    if len(jobs) >= self._max_jobs:
                        break
                    if job.id not in seen_ids:
                        seen_ids.add(job.id)
                        jobs.append(job)
                        self._delay(extra_min=0.3, extra_max=0.8)
            else:
                self._wait_for_cards(page, timeout=20_000)
                self._delay()
                cards = self._find_job_cards(page)
                if not cards:
                    self.log(
                        f"  ⚠️  No job cards found on page {current_page} — "
                        "stopping pagination."
                    )
                    break
                self.log(f"  Found {len(cards)} cards on page {current_page}")
                for card in cards:
                    if len(jobs) >= self._max_jobs:
                        break
                    try:
                        job = self._parse_card(card, page)
                        if job and job.id not in seen_ids:
                            seen_ids.add(job.id)
                            jobs.append(job)
                            self._delay(extra_min=0.5, extra_max=1.5)
                    except Exception as exc:
                        self.log_error("Card parse error", exc)

            added = len(jobs) - n_before
            if added == 0:
                break
            if not self._kalibrr_should_fetch_next_page(
                page, current_page, max_pages, len(jobs), added
            ):
                break

            current_page += 1
            self._delay()

        return jobs

    def _kalibrr_next_meta(self, page: "Page") -> dict:
        try:
            return page.evaluate(
                """() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (!el) return {};
                    try {
                        const d = JSON.parse(el.textContent);
                        const pp = d.props?.pageProps || {};
                        return {
                            count: Number(pp.count) || 0,
                            jobslen: (pp.jobs || []).length,
                        };
                    } catch (e) {
                        return {};
                    }
                }"""
            )
        except Exception:
            return {}

    def _kalibrr_should_fetch_next_page(
        self,
        page: "Page",
        current_page: int,
        max_pages: int,
        total_collected: int,
        added_this_page: int,
    ) -> bool:
        if total_collected >= self._max_jobs or current_page >= max_pages:
            return False
        if added_this_page <= 0:
            return False
        meta = self._kalibrr_next_meta(page)
        total = int(meta.get("count") or 0)
        if total and total_collected >= total:
            return False
        return True

    def _extract_jobs_from_next_data(self, page: "Page") -> list[Job]:
        try:
            records = page.evaluate(
                """() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (!el) return [];
                    try {
                        const d = JSON.parse(el.textContent);
                        const jobs = d.props?.pageProps?.jobs;
                        return Array.isArray(jobs) ? jobs : [];
                    } catch (e) {
                        return [];
                    }
                }"""
            )
        except Exception:
            return []

        if not records:
            return []

        out: list[Job] = []
        for rec in records:
            job = self._job_from_kalibrr_next_record(rec)
            if job:
                out.append(job)
        return out

    @staticmethod
    def _strip_html_basic(html: str) -> str:
        if not html:
            return ""
        t = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", t).strip()[:8000]

    def _kalibrr_location_from_record(self, rec: dict) -> str:
        gl = rec.get("googleLocation")
        if isinstance(gl, dict):
            for key in ("name", "formatted_address", "formattedAddress", "label"):
                v = gl.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(gl, str) and gl.strip():
            return gl.strip()
        return ""

    def _job_from_kalibrr_next_record(self, rec: object) -> Optional[Job]:
        if not isinstance(rec, dict):
            return None
        title = (rec.get("name") or "").strip()
        jid = rec.get("id")
        if not title or jid is None:
            return None

        url = f"{_SEARCH_URL}/{jid}"
        company = (rec.get("companyName") or "").strip()
        comp = rec.get("company")
        if not company and isinstance(comp, dict):
            company = (comp.get("name") or "").strip()
        if not company:
            company = "Unknown Company"

        location = self._kalibrr_location_from_record(rec)
        description = self._strip_html_basic(str(rec.get("description") or ""))

        raw_date = rec.get("activationDate") or rec.get("createdAt") or ""
        posted_at = parse_posted_date(str(raw_date)) if raw_date else None

        loc_type: Optional[LocationType] = None
        if rec.get("isWorkFromHome"):
            loc_type = LocationType.REMOTE
        elif rec.get("isHybrid"):
            loc_type = LocationType.HYBRID
        if loc_type is None:
            loc_type = detect_location_type(title, description, location)

        return Job(
            id=make_job_id(title, company, location),
            title=title,
            company=company,
            location=location or None,
            location_type=loc_type,
            source=self.source_name,
            url=url,
            description=description or None,
            posted_at=posted_at,
            easy_apply=False,
        )

    # ─── Card parser ──────────────────────────────────────────────────────────

    def _parse_card(self, card, page: "Page") -> Optional[Job]:
        """Parse a single job card into a Job object."""

        # ── Title ──────────────────────────────────────────────────────────
        title = self._try_selectors_text(card, _SEL["card_title"])
        if not title:
            return None

        # ── URL ────────────────────────────────────────────────────────────
        url = self._try_selectors_attr(card, _SEL["card_link"], "href")
        if not url:
            url = self._href_from_job_anchors(card)
        if not url:
            return None
        url = self._normalise_url(url)

        # ── Company ────────────────────────────────────────────────────────
        company = self._try_selectors_text(card, _SEL["card_company"]) or "Unknown"

        # ── Location ───────────────────────────────────────────────────────
        location = self._try_selectors_text(card, _SEL["card_location"]) or ""

        # ── Posted date ────────────────────────────────────────────────────
        raw_posted = ""
        for sel in _SEL["card_posted"]:
            try:
                el = card.query_selector(sel)
                if el:
                    raw_posted = (
                        el.get_attribute("datetime")
                        or el.get_attribute("title")
                        or (el.inner_text() or "").strip()
                    )
                    if raw_posted:
                        break
            except Exception:
                continue

        # ── Work type / location type ──────────────────────────────────────
        raw_type = self._try_selectors_text(card, _SEL["card_type"]) or ""

        # ── Fetch full description from detail page ────────────────────────
        description, detail_location, detail_type, detail_posted = (
            self._get_job_details(page, url)
        )

        # Prefer detail page values when card fields are empty
        location = location or detail_location
        raw_posted = raw_posted or detail_posted
        raw_type = raw_type or detail_type

        # ── Determine location type ────────────────────────────────────────
        loc_type = _parse_kalibrr_work_type(raw_type) or detect_location_type(
            title, description or "", location
        )

        return Job(
            id=make_job_id(title, company, location),
            title=title.strip(),
            company=company.strip(),
            location=location.strip() if location else None,
            location_type=loc_type,
            source=self.source_name,
            url=url,
            description=description or None,
            posted_at=parse_posted_date(raw_posted),
            easy_apply=False,  # Kalibrr uses its own application system
        )

    # ─── Detail page ─────────────────────────────────────────────────────────

    def _get_job_details(self, page: "Page", url: str) -> tuple[str, str, str, str]:
        """
        Visit the job detail page and extract:
            (description, location, work_type, posted_date)

        Returns empty strings on any failure so a missing detail page never
        prevents the card from being saved.
        """
        description = location = work_type = posted_date = ""

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            self._dismiss_popups(page)

            # Wait for description to render
            try:
                desc_sel = ", ".join(_SEL["detail_description"])
                page.wait_for_selector(desc_sel, timeout=10_000)
            except PWTimeout:
                pass  # Continue with whatever is on the page

            description = self._try_selectors_text(page, _SEL["detail_description"])
            location = self._try_selectors_text(page, _SEL["detail_location"])
            work_type = self._try_selectors_text(page, _SEL["detail_type"])

            # Posted date: prefer datetime attribute on <time> elements
            for sel in _SEL["detail_posted"]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        posted_date = (
                            el.get_attribute("datetime")
                            or el.get_attribute("title")
                            or (el.inner_text() or "").strip()
                        )
                        if posted_date:
                            break
                except Exception:
                    continue

        except Exception as exc:
            self.log_error(f"Detail page error ({url[:70]}…)", exc)

        return description, location, work_type, posted_date

    # ─── DOM helpers ─────────────────────────────────────────────────────────

    def _href_from_job_anchors(self, card) -> str:
        """Resolve job URL when the card root is an anchor or wraps job links."""
        try:
            h = (card.get_attribute("href") or "").strip()
            if h and ("/job-board/" in h or ("/c/" in h and "/jobs/" in h)):
                return h
            for el in card.query_selector_all("a[href]"):
                h = (el.get_attribute("href") or "").strip()
                if "/job-board/" in h or ("/c/" in h and "/jobs/" in h):
                    return h
        except Exception:
            pass
        return ""

    def _find_job_cards(self, page: "Page") -> list:
        """Try each card selector and return the first non-empty result."""
        for sel in _SEL["job_cards"]:
            cards = self._safe_query_all(page, sel)
            if cards:
                return cards
        return []

    def _try_selectors_text(self, element, selectors: list[str]) -> str:
        """
        Try each selector in order and return the inner text of the first
        matching element, or an empty string if none match.
        """
        for sel in selectors:
            text = self._safe_inner_text(element, sel)
            if text:
                return text.strip()
        return ""

    def _try_selectors_attr(self, element, selectors: list[str], attr: str) -> str:
        """
        Try each selector in order and return the given attribute value of the
        first matching element, or an empty string if none match.
        """
        for sel in selectors:
            value = self._safe_get_attribute(element, sel, attr)
            if value:
                return value.strip()
        return ""

    def _wait_for_cards(self, page: "Page", timeout: int = 25_000) -> None:
        """Wait until at least one known job card selector is visible."""
        for sel in _SEL["job_cards"]:
            try:
                page.wait_for_selector(sel, timeout=timeout)
                return
            except PWTimeout:
                continue
        self.log("  ⚠️  Timed out waiting for job cards.")

    def _has_next_page(self, page: "Page") -> bool:
        """Return True if a 'Next page' control exists and is not disabled."""
        for sel in _SEL["next_page"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    disabled = el.get_attribute("disabled") or el.get_attribute(
                        "aria-disabled"
                    )
                    if not disabled or disabled.lower() == "false":
                        return True
            except Exception:
                continue
        return False

    def _dismiss_popups(self, page: "Page") -> None:
        """
        Click away Kalibrr login prompts, cookie banners, and other modals
        that may obscure job content.
        """
        for sel in _SEL["modal_close"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.4)
            except Exception:
                pass

        # Also dismiss any overlay by pressing Escape
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    # ─── URL helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_search_url(title: str, location: str, page_num: int = 1) -> str:
        """
        Build a Kalibrr search URL on kalibrr.com (id-ID home).

        Pagination uses the ``param`` query key (page index as string).
        """
        # Strip country name from location (e.g. "Jakarta, Indonesia" → "Jakarta")
        city = re.sub(r",?\s*indonesia$", "", location, flags=re.IGNORECASE).strip()

        params: dict[str, str] = {
            "keyword": title,
            "location": city,
            "sort": "freshness",
            "param": str(max(1, page_num)),
        }

        return f"{_SEARCH_URL}?{urlencode(params)}"

    @staticmethod
    def _normalise_url(href: str) -> str:
        """Ensure the URL is absolute, prepending the Kalibrr base domain."""
        href = href.strip()
        if href.startswith("http"):
            return href
        if not href.startswith("/"):
            href = "/" + href
        return _BASE_URL + href

    # ─── Location helpers ─────────────────────────────────────────────────────

    def _has_indonesian_locations(self) -> bool:
        """Return True if any configured location mentions Indonesia."""
        return any(
            "indonesia" in loc.lower() or "jakarta" in loc.lower()
            for loc in self.all_locations
        )

    def _get_indonesian_locations(self) -> list[str]:
        """Return only the configured locations that are in Indonesia."""
        return [
            loc
            for loc in self.all_locations
            if "indonesia" in loc.lower() or "jakarta" in loc.lower()
        ]


# ─── Work-type parser ─────────────────────────────────────────────────────────


def _parse_kalibrr_work_type(raw: str) -> Optional[LocationType]:
    """
    Map Kalibrr's work-setup labels to the internal LocationType enum.

    Known Kalibrr labels:
        "Remote"       → REMOTE
        "Hybrid"       → HYBRID
        "On-site"      → ON_SITE
        "Work On-site" → ON_SITE
        "Flexi Hours"  → HYBRID (closest approximation)
    """
    if not raw:
        return None
    text = raw.lower().strip()

    if "remote" in text:
        return LocationType.REMOTE
    if "hybrid" in text or "flexi" in text:
        return LocationType.HYBRID
    if any(w in text for w in ("on-site", "onsite", "office", "on site", "work on")):
        return LocationType.ON_SITE
    return None
