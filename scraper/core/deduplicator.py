import hashlib
import re


def make_job_id(title: str, company: str, location: str = "") -> str:
    """
    Create a stable 16-character unique ID for a job listing.

    The same job posted on multiple platforms (e.g. LinkedIn AND JobStreet)
    will produce the same ID, so duplicates are automatically collapsed.

    Strategy: sha256( normalize(title) | normalize(company) | normalize(location) )
    """
    normalized = f"{_normalize(title)}|{_normalize(company)}|{_normalize(location)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> str:
    """
    Lowercase, collapse whitespace, strip punctuation.

    Examples
    --------
    "  Software Engineer (React) "  →  "software engineer react"
    "Grab Holdings, Inc."           →  "grab holdings inc"
    "Selangor, Malaysia"            →  "selangor malaysia"
    """
    if not text:
        return ""
    text = text.lower().strip()
    # Remove punctuation except hyphens inside words (e.g. "full-stack")
    text = re.sub(r"[^\w\s-]", "", text)
    # Collapse multiple spaces / tabs
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_duplicate(job_id: str, existing_ids: set) -> bool:
    """Return True if this job ID has already been seen in the current DB."""
    return job_id in existing_ids
