from __future__ import annotations

from typing import Optional

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str, timeout: float = 45.0) -> Optional[str]:
    """
    GET a URL and return response body text, or None on network / HTTP errors.
    """
    try:
        with httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except (httpx.HTTPError, OSError):
        return None
