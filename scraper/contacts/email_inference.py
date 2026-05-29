from __future__ import annotations

import re
from typing import List, Optional

from core.models import Contact, EmailStatus
from contacts.base import split_name
from contacts.domain_resolver import has_mx


def _clean(token: str) -> str:
    """Lowercase and strip anything that isn't a-z (drops accents crudely)."""
    return re.sub(r"[^a-z]", "", token.lower())


def email_patterns(full_name: str, domain: str) -> List[str]:
    """Common corporate email patterns for *full_name* @ *domain*, best guess first."""
    first, last = split_name(full_name)
    first, last = _clean(first), _clean(last)
    if not first:
        return []
    if not last:
        return [f"{first}@{domain}"]

    f = first[0]
    return [
        f"{first}.{last}@{domain}",   # jane.doe@      (most common)
        f"{first}{last}@{domain}",    # janedoe@
        f"{f}{last}@{domain}",        # jdoe@
        f"{first}@{domain}",          # jane@
        f"{first}_{last}@{domain}",   # jane_doe@
        f"{f}.{last}@{domain}",       # j.doe@
    ]


class EmailInferenceEnricher:
    """Fills a best-guess email for contacts that have a real name but no address.

    Verification is deliberately limited to an MX-record check on the domain
    (no SMTP mailbox probing). A guessed address therefore carries email_status
    GUESSED, upgraded to MX_VALID only if the domain demonstrably accepts mail.
    """

    def __init__(self, config: dict) -> None:
        self._cfg = config.get("contact_outreach", {}).get("email_inference", {})
        self.verify_mx: bool = bool(self._cfg.get("verify_mx", True))

    def enrich(self, contacts: List[Contact], domain: Optional[str]) -> None:
        """Mutate *contacts* in place, adding inferred emails where missing."""
        if not domain:
            return

        domain_has_mx: Optional[bool] = None  # computed lazily, once

        for contact in contacts:
            if contact.email:
                continue  # already has a (published) address
            if not _is_real_person_name(contact.full_name, contact.company):
                continue  # generic mailbox placeholder — can't infer

            patterns = email_patterns(contact.full_name, domain)
            if not patterns:
                continue

            guess = patterns[0]  # primary pattern

            if self.verify_mx:
                if domain_has_mx is None:
                    domain_has_mx = has_mx(domain)
                if not domain_has_mx:
                    contact.email = guess
                    contact.email_status = EmailStatus.INVALID
                    contact.notes = _append_note(
                        contact.notes, "Domain has no MX records; email likely undeliverable."
                    )
                    continue
                status = EmailStatus.MX_VALID
            else:
                status = EmailStatus.GUESSED

            contact.email = guess
            contact.email_status = status
            contact.notes = _append_note(
                contact.notes,
                f"Email inferred (pattern guess). Alternatives: {', '.join(patterns[1:4])}",
            )


def _is_real_person_name(full_name: str, company: str) -> bool:
    """False for generic placeholders like 'Acme (info@)'."""
    if not full_name or full_name.startswith(company):
        return False
    return len(full_name.split()) >= 2


def _append_note(existing: Optional[str], addition: str) -> str:
    return f"{existing}\n{addition}".strip() if existing else addition
