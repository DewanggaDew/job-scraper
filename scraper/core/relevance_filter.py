from __future__ import annotations

from typing import List


def is_relevant_title(
    title: str,
    allowed_keywords: List[str],
    blocked_keywords: List[str] | None = None,
) -> bool:
    """
    Return True if *title* matches at least one allowed keyword and
    does not match any blocked keyword.  All comparisons are
    case-insensitive substring matches.
    """
    normalised = title.lower().strip()
    if not normalised:
        return False

    if blocked_keywords:
        for kw in blocked_keywords:
            if kw.lower() in normalised:
                return False

    for kw in allowed_keywords:
        if kw.lower() in normalised:
            return True

    return False


def filter_relevant_jobs(
    jobs: list,
    allowed_keywords: List[str],
    blocked_keywords: List[str] | None = None,
) -> tuple[list, int]:
    """
    Filter a list of Job objects, keeping only those with relevant titles.
    Returns (relevant_jobs, filtered_count).
    """
    relevant: list = []
    filtered = 0
    for job in jobs:
        if is_relevant_title(job.title, allowed_keywords, blocked_keywords):
            relevant.append(job)
        else:
            filtered += 1
    return relevant, filtered
