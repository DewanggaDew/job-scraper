from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from core.models import Contact, ContactSource
from contacts.base import BaseContactFinder, classify_role, make_contact_id

# Role keywords appended to the company search, one search per keyword.
_SEARCH_TERMS = {
    "recruiter": "recruiter",
    "talent_acquisition": "talent acquisition",
    "hiring_manager": "engineering manager",
    "hr": "human resources",
}


class LinkedInPeopleFinder(BaseContactFinder):
    """⚠️  Phase 3 — opt-in only. Scrapes LinkedIn People search for company staff.

    Scraping people violates LinkedIn's Terms of Service and risks a ban on the
    SAME account used for auto-apply. This finder is only constructed when
    contact_outreach.sources.linkedin is true. It reuses the proven session
    handling from auto_applier (cookie injection / form login), opens a SINGLE
    shared browser session reused across companies, and applies aggressive
    delays and a hard per-company cap.
    """

    source_name = "linkedin"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.linkedin_email = os.environ.get("LINKEDIN_EMAIL")
        self.linkedin_password = os.environ.get("LINKEDIN_PASSWORD")
        self.cookies_json = os.environ.get("LINKEDIN_COOKIES")
        self.headless = bool(config.get("scraping", {}).get("headless", True))

        self._pw = None
        self._browser = None
        self._page = None
        self._session_failed = False

        print(
            "  [Contacts:linkedin] ⚠️  LinkedIn people search is ENABLED. "
            "This violates LinkedIn ToS and can get the account banned. "
            "Use sparingly and at your own risk."
        )

    # ─── Finder interface ────────────────────────────────────────────────────────

    def find(
        self,
        company: str,
        domain: Optional[str],
        related_job: Optional[Dict[str, Any]] = None,
    ) -> List[Contact]:
        if not PLAYWRIGHT_AVAILABLE or self._session_failed:
            return []

        page = self._ensure_session()
        if page is None:
            return []

        job_id = related_job.get("related_job_id") if related_job else None
        contacts: List[Contact] = []
        seen: set[str] = set()

        # Only search the role buckets the user wants.
        terms = [
            term
            for role, term in _SEARCH_TERMS.items()
            if self.role_wanted_str(role)
        ]

        for term in terms:
            query = quote_plus(f"{company} {term}")
            url = f"https://www.linkedin.com/search/results/people/?keywords={query}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                time.sleep(random.uniform(3, 6))
                cards = page.query_selector_all("li.reusable-search__result-container") or []
                for card in cards[:5]:
                    parsed = self._parse_card(card)
                    if not parsed:
                        continue
                    name, title, profile_url = parsed
                    if profile_url in seen:
                        continue
                    seen.add(profile_url)
                    role = classify_role(title)
                    if not self.role_wanted(role):
                        continue
                    contacts.append(
                        Contact(
                            id=make_contact_id(name, company, None, profile_url),
                            company=company,
                            company_domain=domain,
                            full_name=name,
                            title=title,
                            role=role,
                            linkedin_url=profile_url,
                            source=ContactSource.LINKEDIN,
                            confidence=0.7,
                            related_job_id=job_id,
                        )
                    )
                    if len(contacts) >= self.max_contacts_per_company:
                        return contacts
            except Exception as exc:
                self.log_error(f"search failed for '{company} {term}'", exc)

            # Aggressive, randomised delay between searches to look human.
            time.sleep(random.uniform(8, 16))

        return contacts

    def role_wanted_str(self, role_value: str) -> bool:
        if not self.target_roles:
            return True
        return role_value in self.target_roles

    # ─── Session management ───────────────────────────────────────────────────────

    def _ensure_session(self):
        """Lazily open one shared, authenticated browser session."""
        if self._page is not None:
            return self._page

        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Asia/Kuala_Lumpur",
            )
            if self.cookies_json:
                try:
                    context.add_cookies(json.loads(self.cookies_json))
                except Exception as exc:
                    self.log_error("cookie injection failed", exc)

            page = context.new_page()
            if not self._authenticated(page):
                if self.linkedin_email and self.linkedin_password:
                    self._login(page)
                else:
                    self.log_error("no valid LinkedIn session (cookies/credentials).")
                    self._session_failed = True
                    self._teardown()
                    return None

            self._page = page
            return page
        except Exception as exc:
            self.log_error("could not start LinkedIn session", exc)
            self._session_failed = True
            self._teardown()
            return None

    def _authenticated(self, page) -> bool:
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            return "login" not in page.url and not page.query_selector("input#username")
        except Exception:
            return False

    def _login(self, page) -> None:
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        page.fill("input#username", self.linkedin_email)
        page.fill("input#password", self.linkedin_password)
        page.click('button[type="submit"]')
        page.wait_for_url("**/feed/**", timeout=20000)
        time.sleep(random.uniform(2, 4))

    def _parse_card(self, card) -> Optional[tuple[str, str, str]]:
        """Extract (name, title, profile_url) from a people-search result card."""
        try:
            link = card.query_selector("a[href*='/in/']")
            if not link:
                return None
            profile_url = (link.get_attribute("href") or "").split("?")[0]

            name_el = card.query_selector("span[aria-hidden='true']")
            name = (name_el.inner_text() if name_el else "").strip()
            if not name or name.lower() in ("linkedin member",):
                return None

            title_el = card.query_selector(".entity-result__primary-subtitle")
            title = (title_el.inner_text() if title_el else "").strip()

            return name, title, profile_url
        except Exception:
            return None

    def _teardown(self) -> None:
        for closer in (
            lambda: self._browser.close() if self._browser else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                closer()
            except Exception:
                pass
        self._browser = None
        self._pw = None
        self._page = None

    def __del__(self):
        self._teardown()
