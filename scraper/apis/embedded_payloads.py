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


def _seek_jobs_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve job list from SEEK_REDUX-shaped JSON (paths vary by release)."""
    if not isinstance(payload, dict):
        return []

    results = payload.get("results")
    if isinstance(results, dict):
        inner = results.get("results")
        if isinstance(inner, dict):
            jobs = inner.get("jobs")
            if isinstance(jobs, list):
                return [j for j in jobs if isinstance(j, dict)]
        jobs = results.get("jobs")
        if isinstance(jobs, list):
            return [j for j in jobs if isinstance(j, dict)]

    for key in ("jobResults", "searchResults", "jobs"):
        block = payload.get(key)
        if isinstance(block, dict):
            jobs = block.get("jobs") or block.get("data")
            if isinstance(jobs, list):
                return [j for j in jobs if isinstance(j, dict)]
        if isinstance(block, list):
            return [j for j in block if isinstance(j, dict)]

    return []


def seek_jobs_from_html(html: str) -> list[dict[str, Any]]:
    """
    ``SEEK_REDUX_DATA`` from JobStreet / SEEK SSR (inline assignment in HTML).
    """
    for pattern in (
        r"window\.SEEK_REDUX_DATA\s*=\s*",
        r"SEEK_REDUX_DATA\s*=\s*",
        r"self\.SEEK_REDUX_DATA\s*=\s*",
    ):
        m = re.search(pattern, html)
        if not m:
            continue
        tail = html[m.end() :].lstrip()
        decoder = JSONDecoder()
        try:
            payload, _ = decoder.raw_decode(tail)
        except json.JSONDecodeError:
            continue
        jobs = _seek_jobs_from_payload(payload if isinstance(payload, dict) else {})
        if jobs:
            return [
                j
                for j in jobs
                if isinstance(j, dict)
                and (
                    (str(j.get("title") or "")).strip()
                    or j.get("id")
                    or j.get("jobId")
                )
            ]
    return []
