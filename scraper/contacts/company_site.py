from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from core.models import Contact, ContactRole, ContactSource, EmailStatus
from contacts.base import (
    BaseContactFinder,
    classify_role,
    looks_like_person_name,
    make_contact_id,
)

# Paths likely to list people or contact addresses.
_CANDIDATE_PATHS = (
    "",
    "about",
    "about-us",
    "team",
    "our-team",
    "people",
    "leadership",
    "careers",
    "contact",
    "contact-us",
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")

# Generic mailbox prefixes that map to a relevant role even without a person name.
_ROLE_PREFIXES: Dict[str, ContactRole] = {
    "recruit": ContactRole.RECRUITER,
    "recruiting": ContactRole.RECRUITER,
    "recruitment": ContactRole.RECRUITER,
    "talent": ContactRole.TALENT_ACQUISITION,
    "hr": ContactRole.HR,
    "people": ContactRole.HR,
    "careers": ContactRole.HR,
    "jobs": ContactRole.HR,
    "hiring": ContactRole.RECRUITER,
}

# Generic prefixes we keep but treat as low-confidence catch-alls.
_CATCHALL_PREFIXES = {"info", "hello", "contact", "hi", "team", "admin", "enquiries", "enquiry"}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CompanySiteFinder(BaseContactFinder):
    """Scrapes a company's own website for published emails and named people.

    Lightweight: plain HTTP fetch + regex (no browser). JS-rendered staff
    directories won't be captured — that's an accepted limitation of the free,
    low-risk path. Names found here (without emails) are later passed to the
    email-inference finder to construct a likely address.
    """

    source_name = "company_site"

    def find(
        self,
        company: str,
        domain: Optional[str],
        related_job: Optional[Dict[str, Any]] = None,
    ) -> List[Contact]:
        if not _HTTPX_AVAILABLE or not domain:
            return []

        job_id = related_job.get("related_job_id") if related_job else None
        contacts: List[Contact] = []
        seen_emails: set[str] = set()
        seen_names: set[str] = set()

        for path in _CANDIDATE_PATHS:
            url = f"https://{domain}/{path}".rstrip("/")
            html = self._fetch(url)
            if not html:
                continue

            # 1. Published emails on this domain.
            for email in self._extract_domain_emails(html, domain):
                if email in seen_emails:
                    continue
                seen_emails.add(email)
                c = self._contact_from_email(email, company, domain, job_id)
                if c and self.role_wanted(c.role):
                    contacts.append(c)

            # 2. Named people with target-role titles (no email yet).
            for name, title in self._extract_people(html):
                key = name.lower()
                if key in seen_names:
                    continue
                seen_names.add(key)
                role = classify_role(title)
                if not self.role_wanted(role):
                    continue
                contacts.append(
                    Contact(
                        id=make_contact_id(name, company, None, None),
                        company=company,
                        company_domain=domain,
                        full_name=name,
                        title=title,
                        role=role,
                        source=ContactSource.COMPANY_SITE,
                        confidence=0.45,
                        related_job_id=job_id,
                    )
                )

            if len(contacts) >= self.max_contacts_per_company * 3:
                break  # plenty to work with; stop hitting more pages
            self._delay()

        return contacts

    # ─── Internals ──────────────────────────────────────────────────────────────

    def _fetch(self, url: str) -> Optional[str]:
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=12.0,
                follow_redirects=True,
            )
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                return resp.text
        except Exception as exc:
            self.log_error(f"fetch failed for {url}", exc)
        return None

    def _extract_domain_emails(self, html: str, domain: str) -> List[str]:
        """Return emails on *domain* (or its subdomains), lowercased & deduped."""
        found = []
        for raw in _EMAIL_RE.findall(html):
            email = raw.lower()
            email_domain = email.split("@", 1)[1]
            if email_domain == domain or email_domain.endswith("." + domain):
                found.append(email)
        return list(dict.fromkeys(found))

    def _contact_from_email(
        self, email: str, company: str, domain: str, job_id: Optional[str]
    ) -> Optional[Contact]:
        local = email.split("@", 1)[0]
        prefix = re.split(r"[._\-]", local)[0]

        role = ContactRole.UNKNOWN
        confidence = 0.2
        full_name = ""

        # Role-y mailbox (recruit@, hr@, talent@ …)
        for key, mapped in _ROLE_PREFIXES.items():
            if local.startswith(key):
                role = mapped
                confidence = 0.4
                break

        # Person-looking address (jane.doe@, jdoe@) → derive a display name.
        if role == ContactRole.UNKNOWN and prefix not in _CATCHALL_PREFIXES:
            parts = [p for p in re.split(r"[._\-]", local) if p.isalpha()]
            if len(parts) >= 2:
                full_name = " ".join(p.capitalize() for p in parts[:2])
                confidence = 0.5

        if not full_name:
            # Generic mailbox — label it for clarity in the dashboard.
            full_name = f"{company} ({local}@)"

        return Contact(
            id=make_contact_id(full_name, company, email, None),
            company=company,
            company_domain=domain,
            full_name=full_name,
            role=role,
            email=email,
            email_status=EmailStatus.MX_VALID,  # published on the live domain
            source=ContactSource.COMPANY_SITE,
            confidence=confidence,
            related_job_id=job_id,
        )

    def _extract_people(self, html: str) -> List[tuple[str, str]]:
        """Heuristic 'Name + Title' extraction from team/about pages.

        Looks for a person-name line immediately followed (within a short window)
        by a line containing a target-role keyword. Noisy by nature — kept at low
        confidence upstream.
        """
        # Convert tags to line breaks so adjacent name/title nodes become lines.
        text = _TAG_RE.sub("\n", html)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        results: List[tuple[str, str]] = []
        for i, line in enumerate(lines):
            if not looks_like_person_name(line):
                continue
            # Look at the next couple of lines for a title.
            for j in range(i + 1, min(i + 3, len(lines))):
                title = lines[j]
                if 3 < len(title) <= 60 and classify_role(title) != ContactRole.UNKNOWN:
                    results.append((line, title))
                    break
        return results
