from __future__ import annotations

import re
import socket
from typing import List, Optional
from urllib.parse import urlparse

try:
    import dns.resolver  # dnspython

    _DNS_AVAILABLE = True
except ImportError:
    _DNS_AVAILABLE = False

# Hosts that are job boards / aggregators, never the employer's own domain.
_JOB_BOARD_HOSTS = (
    "linkedin.com",
    "jobstreet.com",
    "jobstreet.co",
    "glints.com",
    "indeed.com",
    "kalibrr.com",
    "google.com",
    "bit.ly",
    "lnkd.in",
)

# Company-name suffixes to strip before guessing a domain.
_SUFFIX_RE = re.compile(
    r"\b(sdn\.?\s*bhd|bhd|pte\.?\s*ltd|pvt\.?\s*ltd|ltd|llc|inc|gmbh|co|company|corp|"
    r"corporation|group|holdings|technologies|technology|tech|solutions|labs|studio|"
    r"international|global)\b\.?",
    re.IGNORECASE,
)

# TLDs to try, ordered by likelihood for this user's target markets (MY/ID/SG + global).
_CANDIDATE_TLDS = (
    "com",
    "io",
    "co",
    "com.my",
    "com.sg",
    "co.id",
    "ai",
    "tech",
    "net",
)


def _host_is_job_board(host: str) -> bool:
    host = host.lower()
    return any(board in host for board in _JOB_BOARD_HOSTS)


def _registrable_domain(host: str) -> str:
    """Strip a leading 'www.' — keep the rest as-is (good enough for MX checks)."""
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def has_mx(domain: str) -> bool:
    """True if *domain* has MX records (or, as a weaker fallback, resolves at all).

    Uses dnspython when available; otherwise falls back to a plain A-record lookup
    via the stdlib (weaker — confirms the domain exists, not that it accepts mail).
    No SMTP probing is performed.
    """
    domain = domain.strip().lower()
    if not domain:
        return False

    if _DNS_AVAILABLE:
        try:
            answers = dns.resolver.resolve(domain, "MX")
            return len(answers) > 0
        except Exception:
            # No MX — many small sites route mail elsewhere; fall through to A check.
            pass

    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def normalize_company_slug(company: str) -> str:
    """'Acme Technologies Sdn Bhd' → 'acme'. Best-effort, may over-trim."""
    name = _SUFFIX_RE.sub("", company)
    name = re.sub(r"[^a-zA-Z0-9]+", "", name).lower()
    return name


def candidate_domains(company: str) -> List[str]:
    """Generate plausible company domains to test, best guess first."""
    slug = normalize_company_slug(company)
    if not slug:
        return []
    return [f"{slug}.{tld}" for tld in _CANDIDATE_TLDS]


def resolve_domain(company: str, url_hint: Optional[str] = None) -> Optional[str]:
    """Resolve a company name to its email domain.

    1. If *url_hint* points at the employer's own site (not a job board), use it.
    2. Otherwise guess from the company name and confirm the domain has MX records.

    Returns the domain (e.g. 'acme.com') or None if nothing confirmable was found.
    """
    # 1. Trust a non-job-board URL host.
    if url_hint:
        try:
            host = urlparse(url_hint).netloc
            if host and not _host_is_job_board(host):
                domain = _registrable_domain(host)
                if has_mx(domain):
                    return domain
        except Exception:
            pass

    # 2. Guess and verify.
    for domain in candidate_domains(company):
        if has_mx(domain):
            return domain

    return None
