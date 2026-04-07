"""
HTTP-first data access for job boards (embedded SSR JSON, RSS).

Used by scrapers before Playwright so runs work without a browser when the
site returns listings in the initial HTML response.
"""

from apis.embedded_payloads import (
    glints_jobs_from_html,
    kalibrr_jobs_from_html,
    seek_jobs_from_html,
)
from apis.http_fetch import fetch_html
from apis.indeed_rss import build_indeed_rss_url, parse_indeed_rss

__all__ = [
    "build_indeed_rss_url",
    "fetch_html",
    "glints_jobs_from_html",
    "kalibrr_jobs_from_html",
    "parse_indeed_rss",
    "seek_jobs_from_html",
]
