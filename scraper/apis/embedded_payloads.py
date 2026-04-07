from __future__ import annotations

import json
import re
from json import JSONDecoder
from typing import Any


def _next_data_json(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    raw = (m.group(1) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def glints_jobs_from_html(html: str) -> list[dict[str, Any]]:
    """
    ``props.pageProps.initialJobs.jobsInPage`` from Glints Next.js SSR.
    """
    data = _next_data_json(html)
    if not data:
        return []
    initial = data.get("props", {}).get("pageProps", {}).get("initialJobs")
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


def kalibrr_jobs_from_html(html: str) -> list[dict[str, Any]]:
    """``props.pageProps.jobs`` from Kalibrr Next.js SSR."""
    data = _next_data_json(html)
    if not data:
        return []
    jobs = data.get("props", {}).get("pageProps", {}).get("jobs")
    if not isinstance(jobs, list):
        return []
    return [j for j in jobs if isinstance(j, dict)]


def seek_jobs_from_html(html: str) -> list[dict[str, Any]]:
    """
    ``window.SEEK_REDUX_DATA.results.results.jobs`` from JobStreet / SEEK SSR.
    """
    m = re.search(r"window\.SEEK_REDUX_DATA\s*=\s*", html)
    if not m:
        return []
    tail = html[m.end() :].lstrip()
    decoder = JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(tail)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, dict):
        return []
    inner = results.get("results")
    if not isinstance(inner, dict):
        return []
    jobs = inner.get("jobs")
    return jobs if isinstance(jobs, list) else []
