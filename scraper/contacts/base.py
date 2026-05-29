from __future__ import annotations

import hashlib
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.models import Contact, ContactRole

# ─── Role classification ───────────────────────────────────────────────────────
# Ordered most-specific → least. The first bucket whose keywords appear in the
# person's title text wins. Keep these lowercase.

_ROLE_KEYWORDS: List[tuple[ContactRole, tuple[str, ...]]] = [
    (
        ContactRole.TALENT_ACQUISITION,
        ("talent acquisition", "talent partner", "talent acquisition partner", "sourcer", "talent lead"),
    ),
    (
        ContactRole.RECRUITER,
        ("recruiter", "recruitment", "recruiting", "tech recruiter", "technical recruiter"),
    ),
    (
        ContactRole.HR,
        (
            "human resources",
            "people operations",
            "people ops",
            "people partner",
            "people & culture",
            "chief people",
            "hr manager",
            "hr business partner",
            "hrbp",
            "head of people",
        ),
    ),
    (
        ContactRole.HIRING_MANAGER,
        (
            "engineering manager",
            "head of engineering",
            "head of product",
            "engineering lead",
            "team lead",
            "tech lead",
            "vp engineering",
            "vp of engineering",
            "director of engineering",
            "cto",
            "chief technology",
            "product manager",
        ),
    ),
]


def classify_role(title_text: Optional[str]) -> ContactRole:
    """Map a free-text job title to one of the target ContactRole buckets."""
    if not title_text:
        return ContactRole.UNKNOWN
    t = title_text.lower()
    for role, keywords in _ROLE_KEYWORDS:
        if any(kw in t for kw in keywords):
            return role
    return ContactRole.UNKNOWN


def make_contact_id(
    full_name: str, company: str, email: Optional[str], linkedin_url: Optional[str]
) -> str:
    """Stable id: prefer the LinkedIn URL, else name|company|email."""
    if linkedin_url:
        basis = linkedin_url.strip().lower().rstrip("/")
    else:
        basis = f"{full_name.strip().lower()}|{company.strip().lower()}|{(email or '').strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ─── Name helpers (shared by email inference & site parsing) ────────────────────

_NAME_RE = re.compile(r"^[A-Z][a-z'’\-]+(?:\s+[A-Z][a-z'’\-]+){1,2}$")


def looks_like_person_name(text: str) -> bool:
    """Heuristic: 'Jane Doe' / 'Jane Mary Doe' → True; 'Careers Team' → False."""
    text = (text or "").strip()
    return bool(_NAME_RE.match(text))


def split_name(full_name: str) -> tuple[str, str]:
    """Return (first, last) — last is the final token, first is the first token."""
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


# ─── Base finder ────────────────────────────────────────────────────────────────


class BaseContactFinder(ABC):
    """Abstract base for all contact finders.

    Subclasses implement find(); the orchestrator (ContactFinder) calls it once
    per target company. Implementations must:
      • never raise on network/parse failure — return [] instead,
      • respect self.target_roles (filtering is also enforced upstream),
      • call self._delay() between remote requests.
    """

    source_name: str = "base"

    def __init__(self, config: dict) -> None:
        self.config = config
        self._cfg = config.get("contact_outreach", {})
        self.target_roles: List[str] = self._cfg.get("target_roles", [])
        self.max_contacts_per_company: int = int(
            self._cfg.get("max_contacts_per_company", 3)
        )
        scrape_cfg = config.get("scraping", {})
        delay = scrape_cfg.get("delay_between_requests", {})
        self._delay_min = float(delay.get("min_seconds", 3))
        self._delay_max = float(delay.get("max_seconds", 8))

    @abstractmethod
    def find(
        self,
        company: str,
        domain: Optional[str],
        related_job: Optional[Dict[str, Any]] = None,
    ) -> List[Contact]:
        """Return a list of Contact objects for *company*."""
        ...

    # ─── Helpers ────────────────────────────────────────────────────────────────

    def _delay(self) -> None:
        time.sleep(random.uniform(self._delay_min, self._delay_max))

    def role_wanted(self, role: ContactRole) -> bool:
        """True if this role is one of the configured targets (empty = all)."""
        if not self.target_roles:
            return True
        return role.value in self.target_roles

    def log(self, message: str) -> None:
        print(f"  [Contacts:{self.source_name}]  {message}")

    def log_error(self, message: str, exc: Optional[Exception] = None) -> None:
        suffix = f": {exc}" if exc else ""
        print(f"  [Contacts:{self.source_name}] ⚠️  {message}{suffix}")
