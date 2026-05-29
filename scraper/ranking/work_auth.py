from __future__ import annotations

"""
work_auth.py — Work-authorization / visa awareness for scoring
===============================================================
The scraper now searches across many countries (MY, ID, SG, AU, TW, HK, UK,
US). The candidate is only authorised to work in a subset of them, so a role
they cannot legally take without sponsorship should be down-ranked — otherwise
a London job scores the same as a Kuala Lumpur one.

This module is deliberately rule-based (no LLM): country detection plus a scan
for explicit sponsorship language. It returns a score multiplier applied to the
final overall score, plus an `authorized` flag for display in the dashboard.
"""

import re
from typing import Optional, Tuple

# Map each supported country key → location/city keywords that imply it.
# Keys must match the keys used in config.yaml → candidate_profile.work_authorization.
_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "malaysia": [
        "malaysia", "kuala lumpur", "selangor", "petaling jaya", "cyberjaya",
        "shah alam", "putrajaya", "penang", "johor", "subang", "klang",
    ],
    "indonesia": [
        "indonesia", "jakarta", "tangerang", "bekasi", "bsd", "bandung",
        "surabaya", "depok", "yogyakarta",
    ],
    "singapore": ["singapore"],
    "australia": [
        "australia", "sydney", "melbourne", "brisbane", "perth", "canberra",
        "adelaide",
    ],
    "taiwan": ["taiwan", "taipei", "taichung", "kaohsiung", "hsinchu"],
    "hong_kong": ["hong kong", "hongkong"],
    "united_kingdom": [
        "united kingdom", "england", "scotland", "wales", "london",
        "manchester", "birmingham", "edinburgh", "cambridge",
    ],
    "united_states": [
        "united states", "u.s.a", "u.s.", "new york", "san francisco",
        "california", "seattle", "austin", "boston", "chicago", "remote, us",
    ],
}

# Word-boundary-safe abbreviations handled separately to avoid false hits
# (e.g. "uk" inside "Kerja UKM", "us" inside "campus").
_ABBREV_KEYWORDS: dict[str, list[str]] = {
    "united_kingdom": ["uk"],
    "united_states": ["usa", "us"],
}

# Phrases that indicate the employer will NOT sponsor a visa / wants locals only.
_NO_SPONSORSHIP_SIGNALS: list[str] = [
    "no visa sponsorship",
    "not able to sponsor",
    "unable to sponsor",
    "cannot sponsor",
    "no sponsorship",
    "without sponsorship",
    "do not provide sponsorship",
    "does not offer sponsorship",
    "sponsorship is not available",
    "sponsorship not available",
    "local candidates only",
    "locals only",
    "must be a citizen",
    "citizens only",
    "permanent resident",
    "must have the right to work",
    "must be authorized to work",
    "must be authorised to work",
    "must already be eligible to work",
    "valid work permit required",
    "existing work authorization",
]

# Phrases that indicate sponsorship / relocation IS supported.
_SPONSORSHIP_SIGNALS: list[str] = [
    "visa sponsorship available",
    "we sponsor",
    "will sponsor",
    "sponsorship provided",
    "sponsorship is available",
    "offer sponsorship",
    "relocation support",
    "relocation assistance",
    "relocation package",
    "open to international",
    "international candidates welcome",
    "visa support",
]


def detect_country(location: str, description: str = "") -> Optional[str]:
    """Best-effort detection of the job's country from its location string.

    Falls back to scanning the description. Returns a country key matching
    _COUNTRY_KEYWORDS, or None when nothing recognisable is found.
    """
    # Location is the strongest signal — check it first and on its own.
    loc_country = _match_country(location or "")
    if loc_country:
        return loc_country
    # Description is noisier; only use it as a fallback.
    return _match_country(description or "")


def _match_country(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()

    # Full keywords (substring is safe — these are multi-char place names).
    for country, keywords in _COUNTRY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return country

    # Abbreviations need word boundaries to avoid false positives.
    for country, abbrevs in _ABBREV_KEYWORDS.items():
        for ab in abbrevs:
            if re.search(rf"(?<![a-z]){re.escape(ab)}(?![a-z])", t):
                return country

    return None


def _has_any(text: str, signals: list[str]) -> bool:
    return any(sig in text for sig in signals)


def assess_work_authorization(
    location: Optional[str],
    description: Optional[str],
    work_authorization: dict,
    factors: dict,
) -> Tuple[float, Optional[bool], str]:
    """Assess whether the candidate can work this job and how to weight it.

    Returns ``(factor, authorized, note)`` where:
      • factor      — multiplier in (0, 1] applied to the overall match score
      • authorized  — True / False / None (unknown country → don't penalise)
      • note        — short human-readable explanation for the dashboard
    """
    unauthorized_factor = float(factors.get("unauthorized_factor", 0.5))
    no_sponsorship_factor = float(factors.get("no_sponsorship_factor", 0.2))
    sponsorship_available_factor = float(factors.get("sponsorship_available_factor", 0.95))

    country = detect_country(location or "", description or "")

    # Unknown country (e.g. "Remote", blank): don't penalise — we can't prove
    # the candidate is ineligible, and false negatives hide good remote roles.
    if country is None:
        return 1.0, None, ""

    authorized = bool(work_authorization.get(country, False))
    pretty = country.replace("_", " ").title()

    if authorized:
        return 1.0, True, f"Authorized to work in {pretty}"

    desc_l = (description or "").lower()
    if _has_any(desc_l, _NO_SPONSORSHIP_SIGNALS):
        return no_sponsorship_factor, False, f"No visa sponsorship — not eligible ({pretty})"
    if _has_any(desc_l, _SPONSORSHIP_SIGNALS):
        return sponsorship_available_factor, False, f"Sponsorship may be available ({pretty})"

    return unauthorized_factor, False, f"May require visa sponsorship ({pretty})"
