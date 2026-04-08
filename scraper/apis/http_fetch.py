from __future__ import annotations

import time
from typing import Optional

import httpx

Headers = dict[str, str]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# If the CDN returns 403/429 but the body still contains SSR payloads, parse it.
_SSR_HINTS = (
    "__NEXT_DATA__",
    "SEEK_REDUX_DATA",
    "jobsInPage",
    '"jobId"',
    "initialJobs",
)


def fetch_html(
    url: str,
    timeout: float = 45.0,
    extra_headers: Optional[Headers] = None,
) -> Optional[str]:
    """
    GET a URL and return response body text, or None on network / hard errors.

    Some job boards return 403/429 while still sending HTML that embeds
    ``__NEXT_DATA__`` or ``SEEK_REDUX_DATA``; we keep that body for parsing.
    """
    headers: Headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(url)
            text = response.text
            if response.status_code < 400:
                return text
            if response.status_code in (401, 403, 429, 500, 502, 503) and len(
                text
            ) > 4000:
                if any(h in text for h in _SSR_HINTS):
                    return text
            return None
    except (httpx.HTTPError, OSError):
        return None


def fetch_text_retry(
    url: str,
    timeout: float = 45.0,
    attempts: int = 3,
    base_delay_s: float = 2.0,
    extra_headers: Optional[Headers] = None,
) -> Optional[str]:
    """GET with a few retries (for RSS / flaky edges)."""
    last: Optional[str] = None
    for i in range(max(1, attempts)):
        last = fetch_html(url, timeout=timeout, extra_headers=extra_headers)
        if last:
            return last
        if i + 1 < attempts:
            time.sleep(base_delay_s * (i + 1))
    return last
