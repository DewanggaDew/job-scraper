from __future__ import annotations

import asyncio
import os
import random
import time
from abc import ABC, abstractmethod
from typing import Optional

import yaml
from core.models import Job

# ─── Base Scraper ─────────────────────────────────────────────────────────────


class BaseScraper(ABC):
    """
    Abstract base class for all job-board scrapers.

    Subclasses must implement:
        scrape() → list[Job]

    Provides:
        • config loading
        • random delay helper (anti-bot courtesy)
        • shared Playwright browser setup
        • safe text / attribute extraction helpers
        • logging helpers
    """

    source_name: str = "base"

    def __init__(self, config: dict) -> None:
        self.config = config
        self._prefs = config.get("job_preferences", {})
        self._scrape_cfg = config.get("scraping", {})
        self._delay_min: float = float(
            self._scrape_cfg.get("delay_between_requests", {}).get("min_seconds", 3)
        )
        self._delay_max: float = float(
            self._scrape_cfg.get("delay_between_requests", {}).get("max_seconds", 8)
        )
        self._max_jobs: int = int(self._scrape_cfg.get("max_jobs_per_source", 50))
        self._headless: bool = bool(self._scrape_cfg.get("headless", True))

    # ─── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def scrape(self) -> list[Job]:
        """
        Run the scraper and return a list of Job objects.

        Implementations should:
        1. Iterate over all relevant title × location combinations from config.
        2. Call self._delay() between requests.
        3. Catch per-result exceptions and log them without aborting the run.
        4. Return an empty list (not raise) when the site is unreachable.
        """
        ...

    # ─── Config helpers ───────────────────────────────────────────────────────

    @property
    def titles(self) -> list[str]:
        return self._prefs.get("titles", [])

    @property
    def onsite_locations(self) -> list[str]:
        return self._prefs.get("locations", {}).get("on_site", [])

    @property
    def remote_locations(self) -> list[str]:
        return self._prefs.get("locations", {}).get("remote", [])

    @property
    def all_locations(self) -> list[str]:
        """Deduplicated union of on-site and remote locations."""
        seen: set[str] = set()
        result: list[str] = []
        for loc in self.onsite_locations + self.remote_locations:
            if loc not in seen:
                seen.add(loc)
                result.append(loc)
        return result

    # ─── Delay / rate-limiting ────────────────────────────────────────────────

    def _delay(self, extra_min: float = 0.0, extra_max: float = 0.0) -> None:
        """
        Sleep for a random duration between [min, max] seconds.
        Optionally add extra seconds to the bounds for slower operations.
        """
        lo = self._delay_min + extra_min
        hi = self._delay_max + extra_max
        seconds = random.uniform(lo, hi)
        time.sleep(seconds)

    # ─── Playwright helpers ───────────────────────────────────────────────────

    def _get_playwright_launch_options(self) -> dict:
        """
        Return a dict of kwargs for playwright.chromium.launch().
        Sets headless mode and common stealth args to reduce bot detection.
        """
        return {
            "headless": self._headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1440,900",
                "--start-maximized",
            ],
        }

    def _get_browser_context_options(self) -> dict:
        """
        Return a dict of kwargs for browser.new_context().
        Spoofs a realistic user-agent and viewport.
        """
        return {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1440, "height": 900},
            "locale": "en-US",
            "timezone_id": "Asia/Kuala_Lumpur",
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

    def _safe_inner_text(
        self, page_or_element, selector: str, default: str = ""
    ) -> str:
        """
        Return inner text of the first element matching *selector*, or *default*.
        Swallows all exceptions so a missing element never aborts a scrape.
        """
        try:
            el = page_or_element.query_selector(selector)
            if el:
                return (el.inner_text() or "").strip()
        except Exception:
            pass
        return default

    def _safe_get_attribute(
        self,
        page_or_element,
        selector: str,
        attribute: str,
        default: str = "",
    ) -> str:
        """
        Return an attribute value from the first matching element, or *default*.
        """
        try:
            el = page_or_element.query_selector(selector)
            if el:
                value = el.get_attribute(attribute)
                return (value or "").strip()
        except Exception:
            pass
        return default

    def _safe_query_all(self, page_or_element, selector: str) -> list:
        """
        Return all elements matching *selector* as a list.
        Returns an empty list on any exception.
        """
        try:
            return page_or_element.query_selector_all(selector) or []
        except Exception:
            return []

    def _wait_and_select(
        self,
        page,
        selector: str,
        timeout: int = 10_000,
    ):
        """
        Wait for an element to appear and return it, or return None on timeout.
        *timeout* is in milliseconds.
        """
        try:
            page.wait_for_selector(selector, timeout=timeout)
            return page.query_selector(selector)
        except Exception:
            return None

    # ─── Logging helpers ──────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        """Print a prefixed log line, e.g.  [LinkedIn]  message"""
        print(f"  [{self.source_name.capitalize()}]  {message}")

    def log_error(self, message: str, exc: Optional[Exception] = None) -> None:
        """Print a prefixed error line."""
        suffix = f": {exc}" if exc else ""
        print(f"  [{self.source_name.capitalize()}] ❌  {message}{suffix}")

    def log_found(self, count: int, title: str = "", location: str = "") -> None:
        where = f" for '{title}' in '{location}'" if title or location else ""
        self.log(f"Found {count} jobs{where}")

    # ─── Class factory ────────────────────────────────────────────────────────

    @classmethod
    def from_config_file(cls, config_path: Optional[str] = None) -> "BaseScraper":
        """
        Instantiate the scraper from a YAML config file.

        Args:
            config_path: Absolute path to config.yaml.  If None, resolves to
                         <scraper_root>/config.yaml automatically.
        """
        if config_path is None:
            scraper_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(scraper_root, "config.yaml")

        with open(config_path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)

        return cls(config)  # type: ignore[call-arg]
