from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

from core.database import (
    get_companies_needing_contacts,
    get_existing_contact_ids,
    get_job_by_id,
    upsert_contacts_batch,
)
from core.models import Contact, ContactStatus, ScrapeSummary

from contacts.base import BaseContactFinder
from contacts.company_site import CompanySiteFinder
from contacts.domain_resolver import resolve_domain
from contacts.email_inference import EmailInferenceEnricher


class ContactFinder:
    """Orchestrates contact discovery for companies behind the user's matches.

    Shaped like AutoApplier: config-driven, gated by an `enabled` flag, with hard
    per-run caps. For each qualifying company it resolves a domain, runs the
    enabled discovery finders, infers/verifies emails, optionally drafts an
    outreach message, then upserts the results. Nothing is ever sent.
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.cfg = config.get("contact_outreach", {})
        self.enabled = bool(self.cfg.get("enabled", False))
        self.min_score = float(self.cfg.get("target_min_score", 70))
        self.target_statuses: List[str] = self.cfg.get("target_statuses", [])
        self.max_companies = int(self.cfg.get("max_companies_per_run", 10))
        self.max_per_company = int(self.cfg.get("max_contacts_per_company", 3))
        self.sources: Dict[str, bool] = self.cfg.get("sources", {})
        self.draft_messages = bool(self.cfg.get("draft_messages", False))

        self.enricher = EmailInferenceEnricher(config)
        self._cv_text_cache: Optional[str] = None
        self._drafter = None  # lazily built

    # ─── Public entry ───────────────────────────────────────────────────────────

    def run(self, summary: Optional[ScrapeSummary] = None) -> int:
        """Find and store contacts. Returns the number of new contacts saved."""
        if not self.enabled:
            print("  [ContactFinder] Disabled in config.yaml. Skipping.")
            return 0

        companies = get_companies_needing_contacts(
            min_score=self.min_score,
            statuses=self.target_statuses or None,
            limit=self.max_companies,
        )
        if not companies:
            print("  [ContactFinder] No companies need contacts this run.")
            return 0

        print(f"  [ContactFinder] Processing {len(companies)} companies …")
        finders = self._build_finders()
        if not finders:
            print("  [ContactFinder] No discovery sources enabled. Skipping.")
            return 0

        existing_ids = get_existing_contact_ids()
        all_new: List[Contact] = []

        for entry in companies:
            company = entry["company"]
            try:
                contacts = self._process_company(entry, finders)
            except Exception as exc:
                print(f"  [ContactFinder] ⚠️ {company} failed: {exc}")
                traceback.print_exc()
                if summary:
                    summary.add_error("contact_finder", f"{company}: {exc}")
                contacts = []

            if summary:
                summary.companies_processed += 1

            for c in contacts:
                if c.id in existing_ids:
                    continue
                existing_ids.add(c.id)
                all_new.append(c)

        if not all_new:
            print("  [ContactFinder] No new contacts found.")
            return 0

        print(f"  [ContactFinder] Saving {len(all_new)} new contacts …")
        errors = upsert_contacts_batch(all_new)
        saved = len(all_new) - errors
        if summary:
            summary.contacts_found += saved
            if errors:
                summary.add_error("contact_finder", f"{errors} contact(s) failed to save.")
        print(f"  [ContactFinder] ✅ {saved} saved | {errors} failed")
        return saved

    # ─── Internals ──────────────────────────────────────────────────────────────

    def _build_finders(self) -> List[BaseContactFinder]:
        finders: List[BaseContactFinder] = []
        if self.sources.get("company_site", True):
            finders.append(CompanySiteFinder(self.config))
        if self.sources.get("linkedin", False):
            # Phase 3 — opt-in; ToS/ban risk. Imported lazily so the dependency
            # only matters when actually enabled.
            try:
                from contacts.linkedin_people import LinkedInPeopleFinder

                finders.append(LinkedInPeopleFinder(self.config))
            except Exception as exc:
                print(f"  [ContactFinder] ⚠️ LinkedIn finder unavailable: {exc}")
        return finders

    def _process_company(
        self, entry: Dict[str, Any], finders: List[BaseContactFinder]
    ) -> List[Contact]:
        company = entry["company"]
        job_id = entry.get("related_job_id")
        domain = resolve_domain(company, entry.get("url"))
        if domain:
            print(f"  [ContactFinder] {company} → {domain}")
        else:
            print(f"  [ContactFinder] {company} → no domain resolved")

        # 1. Discover.
        found: List[Contact] = []
        for finder in finders:
            try:
                found.extend(finder.find(company, domain, entry))
            except Exception as exc:
                finder.log_error(f"find() failed for {company}", exc)

        # 2. Dedup within the company; keep the highest-confidence per id.
        by_id: Dict[str, Contact] = {}
        for c in found:
            prev = by_id.get(c.id)
            if prev is None or c.confidence > prev.confidence:
                by_id[c.id] = c
        contacts = list(by_id.values())

        # 3. Infer / verify emails for named people without an address.
        self.enricher.enrich(contacts, domain)

        # 4. Rank by confidence and cap.
        contacts.sort(key=lambda c: c.confidence, reverse=True)
        contacts = contacts[: self.max_per_company]

        # 5. Optionally draft outreach messages.
        if self.draft_messages and contacts:
            related_job = self._load_job(job_id)
            for c in contacts:
                try:
                    c.draft_message = self._draftnow(c, related_job)
                    c.status = ContactStatus.DRAFTED
                except Exception as exc:
                    print(f"  [ContactFinder] ⚠️ draft failed for {c.full_name}: {exc}")

        return contacts

    def _draftnow(self, contact: Contact, related_job: Optional[Dict[str, Any]]) -> str:
        if self._drafter is None:
            from core.outreach import OutreachDrafter

            self._drafter = OutreachDrafter(self.config)
        return self._drafter.draft(contact, related_job, self._cv_text())

    def _load_job(self, job_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not job_id:
            return None
        try:
            return get_job_by_id(job_id)
        except Exception:
            return None

    def _cv_text(self) -> str:
        if self._cv_text_cache is not None:
            return self._cv_text_cache
        try:
            from ranking.cv_parser import load_cv_profiles

            swe, _pm = load_cv_profiles()
            self._cv_text_cache = swe.raw_text or ""
        except Exception:
            self._cv_text_cache = ""
        return self._cv_text_cache
