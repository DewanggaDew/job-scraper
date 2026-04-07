from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

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
        "base_url": "https://glints.com/my/opportunities/jobs/explore",
        "country_code": "MY",
        "domain": "glints.com/my",
    },
    "Indonesia": {
        "base_url": "https://glints.com/id/opportunities/jobs/explore",
        "country_code": "ID",
        "domain": "glints.com/id",
    },
}

# ─── CSS Selectors ────────────────────────────────────────────────────────────
# These are based on Glints' React-rendered DOM as of mid-2025.
# If Glints updates their markup, update the fallbacks below.

_SEL = {
    # Job card container on the explore/search page
    "job_cards": (
        "div[data-testid='job-card'], "
        "article[data-testid='job-card'], "
        "div.JobCardsc__JobcardContainer, "
        "div[class*='JobcardContainer'], "
        "div[class*='JobCard'], "
        "li[class*='JobCard']"
    ),
    # Fields inside a job card
    "card_title": "h3[data-testid='job-title'], h3.JobTitle, h3[class*='JobTitle'], h3",
    "card_company": "span[data-testid='company-name'], span.CompanyName, span[class*='CompanyName'], a[class*='Company']",
    "card_location": "span[data-testid='job-location'], span[class*='Location'], span[class*='location']",
    "card_posted": "span[data-testid='posted-date'], span[class*='PostedDate'], time, span[class*='date']",
    "card_type": "span[data-testid='work-arrangement'], span[class*='WorkArrangement'], span[class*='workArrangement']",
    "card_link": "a[data-testid='job-card-link'], a[class*='JobCard'], a[href*='/opportunities/jobs/']",
    # Job detail page
    "detail_title": "h1[data-testid='job-title'], h1[class*='JobTitle'], h1",
    "detail_company": "a[data-testid='company-name'], span[class*='CompanyName'], h2[class*='CompanyName']",
    "detail_location": "span[data-testid='location'], span[class*='Location']",
    "detail_description": "div[data-testid='job-description'], div[class*='JobDescription'], div[class*='description']",
    "detail_posted": "span[data-testid='posted-date'], time[class*='PostedDate'], span[class*='PostedDate']",
    "detail_type": "span[data-testid='work-arrangement'], div[class*='WorkArrangement']",
    # Pagination
    "next_button": "button[aria-label='Next page'], button[data-testid='next-page'], li.next > a",
    # Load-more pattern (Glints uses infinite scroll on explore page)
    "load_more": "button[data-testid='load-more'], button[class*='LoadMore']",
}


class GlintsScraper(BaseScraper):
    """
    Scrapes job listings from Glints (glints.com/my and glints.com/id).

    Uses Playwright in headless mode to render the React SPA, then extracts
    job cards from the explore/search page.  For each card it visits the
    detail page to capture the full job description.

    Covers:
        • Malaysia  (glints.com/my) — for Selangor / KL listings
        • Indonesia (glints.com/id) — for Jakarta listings
    """

    source_name = "glints"

    def scrape(self) -> list[Job]:
        if not PLAYWRIGHT_AVAILABLE:
            self.log_error(
                "Playwright not installed — pip install playwright && playwright install chromium"
            )
            return []

        jobs: list[Job] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**self._get_playwright_launch_options())
            context = browser.new_context(**self._get_browser_context_options())
            page = context.new_page()

            for title in self.titles:
                for country_name, country_cfg in _COUNTRY_CONFIG.items():
                    # Only scrape countries relevant to the configured locations
                    if not self._should_scrape_country(country_name):
                        continue

                    self.log(f"Searching '{title}' in {country_name} …")
                    try:
                        results = self._scrape_search(page, title, country_cfg)
                        self.log_found(len(results), title, country_name)
                        jobs.extend(results)
                    except Exception as exc:
                        self.log_error(
                            f"Search failed for '{title}' in {country_name}", exc
                        )

                    self._delay()

                    if len(jobs) >= self._max_jobs:
                        self.log(
                            f"Reached max_jobs limit ({self._max_jobs}) — stopping."
                        )
                        break

                if len(jobs) >= self._max_jobs:
                    break

            context.close()
            browser.close()

        self.log(f"✅  Total jobs collected: {len(jobs)}")
        return jobs

    # ─── Search page ─────────────────────────────────────────────────────────

    def _scrape_search(
        self,
        page: "Page",
        title: str,
        country_cfg: dict,
        max_pages: int = 3,
    ) -> list[Job]:
        jobs: list[Job] = []
        url = self._build_search_url(title, country_cfg)

        try:
            page.goto(url, wait_until="load", timeout=45_000)
            self._dismiss_popups(page)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(2_500)

            # Next.js embeds the first page of results in #__NEXT_DATA__ (SSR). The
            # visible list can stay on spinners while this JSON is already present;
            # prefer it so we do not return 0 jobs when the DOM never matches our
            # card selectors.
            next_jobs = self._jobs_from_next_data(page, country_cfg, title)
            if next_jobs:
                self.log(
                    f"  Found {len(next_jobs)} jobs from __NEXT_DATA__ for '{title}'"
                )
                return next_jobs[: self._max_jobs]

            self._wait_for_job_cards(page, timeout=22_000)
        except Exception as exc:
            self.log_error(f"Could not load search page: {url}", exc)
            return jobs

        # Scroll / load-more to fetch more listings (Glints uses infinite scroll)
        self._scroll_to_load_more(page, max_scrolls=4)

        # Prefer harvesting job links from the live DOM — card wrappers change often.
        link_jobs = self._extract_jobs_from_glints_links(page, country_cfg, title)
        if link_jobs:
            self.log(f"  Found {len(link_jobs)} job links on page for '{title}'")
            for job in link_jobs[: self._max_jobs]:
                jobs.append(job)
                self._delay(extra_min=0.5, extra_max=1.5)
            return jobs

        cards = self._safe_query_all(page, _SEL["job_cards"])
        self.log(f"  Found {len(cards)} cards on page for '{title}'")

        for card in cards[: self._max_jobs]:
            try:
                job = self._parse_card(page, card, country_cfg)
                if job:
                    jobs.append(job)
                    self._delay(extra_min=0.5, extra_max=1.5)
            except Exception as exc:
                self.log_error("Card parse error", exc)

        return jobs

    def _jobs_from_next_data(
        self,
        page: "Page",
        country_cfg: dict,
        search_title_hint: str,
    ) -> list[Job]:
        """
        Parse ``props.pageProps.initialJobs.jobsInPage`` from the embedded
        ``#__NEXT_DATA__`` script (Next.js SSR). Avoids relying on React having
        painted job cards.
        """
        raw = self._raw_next_data_job_dicts(page)
        if not raw:
            return []

        jobs: list[Job] = []
        domain = country_cfg["domain"]
        for row in raw:
            if len(jobs) >= self._max_jobs:
                break
            try:
                job = _next_data_row_to_job(row, domain, self.source_name, search_title_hint)
                if job:
                    jobs.append(job)
            except Exception as exc:
                self.log_error("Glints __NEXT_DATA__ row error", exc)
        return jobs

    def _raw_next_data_job_dicts(self, page: "Page") -> list[dict[str, Any]]:
        try:
            script_text = page.evaluate(
                """() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    return el && el.textContent ? el.textContent : '';
                }"""
            )
        except Exception:
            return []

        if not script_text or not isinstance(script_text, str):
            return []

        try:
            data = json.loads(script_text)
        except json.JSONDecodeError:
            return []

        initial = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialJobs")
        )
        if not isinstance(initial, dict):
            return []

        jobs_in_page = initial.get("jobsInPage")
        if not isinstance(jobs_in_page, list):
            return []

        out: list[dict[str, Any]] = []
        for item in jobs_in_page:
            if isinstance(item, dict) and item.get("id") and item.get("title"):
                out.append(item)
        return out

    # ─── Card parser ─────────────────────────────────────────────────────────

    def _parse_card(self, page: "Page", card, country_cfg: dict) -> Optional[Job]:
        # Try each comma-separated fragment separately — a single compound selector
        # string only ever matches the first alternative in some nested DOM trees.
        title = self._first_inner_text_from_list(card, _SEL["card_title"])
        company = self._first_inner_text_from_list(card, _SEL["card_company"])
        location = self._first_inner_text_from_list(card, _SEL["card_location"])
        raw_posted = self._first_inner_text_from_list(card, _SEL["card_posted"])
        raw_type = self._first_inner_text_from_list(card, _SEL["card_type"])

        url = self._first_href_from_list(card, _SEL["card_link"])
        if not url:
            url = self._first_job_opportunity_href(card)
        if not url:
            h = self._safe_get_attribute(card, "a", "href")
            if h and "/opportunities/jobs/" in h:
                url = h
        if not url:
            return None  # Can't apply without a URL

        url = self._normalise_url(url, country_cfg["domain"])

        if not title.strip():
            return None
        if not company.strip():
            company = "Unknown Company"

        # Fetch full description from detail page
        description, detail_location, detail_type, detail_posted = (
            self._get_job_details(page, url)
        )

        # Merge detail data into card data where card data is missing
        location = location or detail_location
        raw_posted = raw_posted or detail_posted
        raw_type = raw_type or detail_type

        # Parse / detect location type
        loc_type = _parse_location_type(raw_type) or detect_location_type(
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
            description=description,
            posted_at=parse_posted_date(raw_posted),
            easy_apply=False,  # Glints uses its own application flow
        )

    # ─── Detail page ─────────────────────────────────────────────────────────

    def _get_job_details(self, page: "Page", url: str) -> tuple[str, str, str, str]:
        """
        Navigate to a job detail page and extract:
            (description, location, work_type, posted_date)
        Returns empty strings on any failure so a missing detail page never
        prevents the card from being saved.
        """
        description = location = work_type = posted_date = ""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            self._dismiss_popups(page)

            # Wait for the description to appear
            try:
                page.wait_for_selector(_SEL["detail_description"], timeout=8_000)
            except PWTimeout:
                pass  # Continue anyway — we might still get partial data

            description = self._first_inner_text_from_list(page, _SEL["detail_description"])
            location = self._first_inner_text_from_list(page, _SEL["detail_location"])
            work_type = self._first_inner_text_from_list(page, _SEL["detail_type"])
            posted_date = self._first_inner_text_from_list(page, _SEL["detail_posted"])

        except Exception as exc:
            self.log_error(f"Detail page error ({url[:60]}…)", exc)

        return description, location, work_type, posted_date

    # ─── Scroll / load more ───────────────────────────────────────────────────

    def _scroll_to_load_more(self, page: "Page", max_scrolls: int = 4) -> None:
        """
        Scroll down the page to trigger Glints' infinite scroll / load-more,
        waiting briefly after each scroll for new cards to render.
        """
        for _ in range(max_scrolls):
            prev_count = len(self._safe_query_all(page, _SEL["job_cards"]))
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.0)  # Give React time to render new cards

            # Click "Load more" button if present
            load_more = page.query_selector(_SEL["load_more"])
            if load_more:
                try:
                    load_more.click()
                    time.sleep(2.0)
                except Exception:
                    pass

            new_count = len(self._safe_query_all(page, _SEL["job_cards"]))
            if new_count == prev_count:
                break  # No new cards loaded — stop scrolling

    def _wait_for_job_cards(self, page: "Page", timeout: int = 15_000) -> None:
        """Wait until at least one job card is visible on the page."""
        try:
            page.wait_for_selector(_SEL["job_cards"], timeout=timeout)
        except PWTimeout:
            self.log(
                "  ⚠️  Timed out waiting for job cards — page may be empty or blocked."
            )

    # ─── Popup / modal dismissal ─────────────────────────────────────────────

    def _dismiss_popups(self, page: "Page") -> None:
        """
        Click away common Glints popups (login prompt, cookies banner, etc.)
        that can obscure job cards.
        """
        dismiss_selectors = [
            "button[aria-label='Close']",
            "button[data-testid='modal-close']",
            "button[class*='CloseButton']",
            "div[class*='Modal'] button[class*='close']",
            # Cookie consent
            "button#onetrust-accept-btn-handler",
            "button[class*='cookie'] button",
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
            except Exception:
                pass

    # ─── URL helpers ─────────────────────────────────────────────────────────

    def _build_search_url(self, title: str, country_cfg: dict) -> str:
        # Match explore SSR query so initialJobs is populated (see canonical
        # ``?country=…&locationName=All+Cities%2FProvinces`` on production).
        params: dict[str, str] = {
            "country": country_cfg["country_code"],
            "locationName": "All Cities/Provinces",
        }
        kw = title.strip()
        if kw:
            params["keyword"] = kw
        return f"{country_cfg['base_url']}?{urlencode(params)}"

    def _normalise_url(self, href: str, domain: str) -> str:
        """Ensure the URL is absolute."""
        if href.startswith("http"):
            return href
        # Relative URL → prepend the appropriate base domain
        base = "https://" + domain
        if not href.startswith("/"):
            href = "/" + href
        return base + href

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _selector_variants(self, selector_csv: str) -> list[str]:
        return [s.strip() for s in selector_csv.split(",") if s.strip()]

    def _first_inner_text_from_list(self, card, selector_csv: str) -> str:
        for sel in self._selector_variants(selector_csv):
            text = self._safe_inner_text(card, sel)
            if text:
                return text
        return ""

    def _first_href_from_list(self, card, selector_csv: str) -> str:
        for sel in self._selector_variants(selector_csv):
            href = self._safe_get_attribute(card, sel, "href")
            if href:
                return href
        return ""

    def _first_job_opportunity_href(self, card) -> str:
        """Any anchor to a Glints job detail inside the card."""
        try:
            for el in card.query_selector_all("a[href]"):
                href = (el.get_attribute("href") or "").strip()
                if "/opportunities/jobs/" in href:
                    return href
        except Exception:
            pass
        return ""

    def _extract_jobs_from_glints_links(
        self,
        page: "Page",
        country_cfg: dict,
        search_title_hint: str,
    ) -> list[Job]:
        """
        Collect unique ``/opportunities/jobs/`` links from the document.
        Card-level selectors often match unrelated nodes; anchors stay stable.
        """
        try:
            rows = page.evaluate(
                """() => {
                    const seen = new Set();
                    const out = [];
                    const host = window.location.host || 'glints.com';
                    for (const a of document.querySelectorAll('a[href]')) {
                        let href = a.getAttribute('href') || '';
                        if (!href.includes('/opportunities/jobs/')) continue;
                        if (href.startsWith('/')) {
                            href = 'https://' + host + href;
                        }
                        const u = href.split('#')[0].split('?')[0];
                        if (seen.has(u)) continue;
                        seen.add(u);
                        const t = (a.innerText || a.getAttribute('aria-label') || '')
                            .trim().replace(/\\s+/g, ' ');
                        out.push({ href: u, anchorText: t.slice(0, 400) });
                    }
                    return out;
                }"""
            )
        except Exception:
            return []

        if not rows:
            return []

        jobs: list[Job] = []
        for row in rows:
            if len(jobs) >= self._max_jobs:
                break
            try:
                href = (row.get("href") or "").strip()
                if not href:
                    continue
                url = self._normalise_url(href, country_cfg["domain"])
                anchor_title = (row.get("anchorText") or "").strip()

                description, detail_location, work_type, posted_date = (
                    self._get_job_details(page, url)
                )
                detail_title = self._first_inner_text_from_list(
                    page, _SEL["detail_title"]
                )
                title = (
                    anchor_title
                    if len(anchor_title) > 2
                    else detail_title.strip()
                )
                if not title:
                    title = search_title_hint or "Job listing"

                company = self._first_inner_text_from_list(
                    page, _SEL["detail_company"]
                ).strip() or "Unknown Company"
                location = (
                    self._first_inner_text_from_list(page, _SEL["detail_location"])
                    or detail_location
                ).strip()

                loc_type = _parse_location_type(work_type) or detect_location_type(
                    title, description or "", location
                )

                jobs.append(
                    Job(
                        id=make_job_id(title, company, location),
                        title=title.strip(),
                        company=company,
                        location=location or None,
                        location_type=loc_type,
                        source=self.source_name,
                        url=url,
                        description=description,
                        posted_at=parse_posted_date(posted_date),
                        easy_apply=False,
                    )
                )
            except Exception as exc:
                self.log_error("Glints link job error", exc)

        return jobs

    def _should_scrape_country(self, country_name: str) -> bool:
        """
        Return True if at least one configured location mentions this country.
        Avoids scraping Indonesian listings when only Malaysian locations are set,
        and vice-versa.
        """
        all_locs = " ".join(self.all_locations).lower()
        return country_name.lower() in all_locs


# ─── Location type parser ─────────────────────────────────────────────────────


def _parse_location_type(raw: str) -> Optional[LocationType]:
    """Parse Glints' work-arrangement label into a LocationType enum value."""
    if not raw:
        return None
    text = raw.lower()
    if "remote" in text:
        return LocationType.REMOTE
    if "hybrid" in text:
        return LocationType.HYBRID
    if any(w in text for w in ("on-site", "onsite", "office", "on site")):
        return LocationType.ON_SITE
    return None


def _glints_iso_posted_at(
    created_at: Optional[str], updated_at: Optional[str]
) -> Optional[datetime]:
    """Prefer createdAt; fall back to updatedAt. Normalise trailing Z for fromisoformat."""
    raw = (created_at or updated_at or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return parse_posted_date(raw)


def _format_glints_api_location(loc: Any) -> str:
    """Build a single location string from hierarchical location + legacy city fields."""
    if not isinstance(loc, dict):
        return ""

    name = (loc.get("name") or loc.get("formattedName") or "").strip()
    parts: list[str] = []
    parents = loc.get("parents")
    if isinstance(parents, list):
        for p in parents:
            if not isinstance(p, dict):
                continue
            fn = (p.get("formattedName") or p.get("name") or "").strip()
            if fn and fn not in parts:
                parts.append(fn)
    if name and name not in parts:
        parts.insert(0, name)
    if parts:
        return ", ".join(parts)

    return name


def _snippet_from_glints_api_row(row: dict[str, Any]) -> Optional[str]:
    """Lightweight text from category + skills when we skip the detail page."""
    lines: list[str] = []
    cat = row.get("hierarchicalJobCategory")
    if isinstance(cat, dict):
        cn = (cat.get("name") or "").strip()
        if cn:
            lines.append(f"Category: {cn}")

    skill_names: list[str] = []
    skills = row.get("skills")
    if isinstance(skills, list):
        for s in skills[:20]:
            if not isinstance(s, dict):
                continue
            sk = s.get("skill")
            if isinstance(sk, dict):
                nm = (sk.get("name") or "").strip()
                if nm:
                    skill_names.append(nm)
    if skill_names:
        lines.append("Skills: " + ", ".join(skill_names))

    return "\n".join(lines) if lines else None


def _next_data_row_to_job(
    row: dict[str, Any],
    domain: str,
    source_name: str,
    search_title_hint: str,
) -> Optional[Job]:
    job_id = str(row.get("id") or "").strip()
    title = (row.get("title") or "").strip()
    if not job_id or not title:
        return None

    company_block = row.get("company")
    company = "Unknown Company"
    if isinstance(company_block, dict):
        company = (company_block.get("name") or "").strip() or company

    loc_text = _format_glints_api_location(row.get("location"))
    if not loc_text:
        city = row.get("city")
        if isinstance(city, dict):
            loc_text = (city.get("name") or "").strip()
    if not loc_text:
        csd = row.get("citySubDivision")
        if isinstance(csd, dict):
            loc_text = (csd.get("name") or "").strip()

    arrangement = row.get("workArrangementOption")
    raw_arr = arrangement if isinstance(arrangement, str) else ""
    loc_type = _parse_location_type(raw_arr) or detect_location_type(
        title, "", loc_text
    )

    url = f"https://{domain}/opportunities/jobs/{job_id}"
    description = _snippet_from_glints_api_row(row)
    posted_at = _glints_iso_posted_at(
        row.get("createdAt") if isinstance(row.get("createdAt"), str) else None,
        row.get("updatedAt") if isinstance(row.get("updatedAt"), str) else None,
    )

    return Job(
        id=make_job_id(title, company, loc_text or search_title_hint or url),
        title=title,
        company=company,
        location=loc_text or None,
        location_type=loc_type,
        source=source_name,
        url=url,
        description=description,
        posted_at=posted_at,
        easy_apply=False,
    )
