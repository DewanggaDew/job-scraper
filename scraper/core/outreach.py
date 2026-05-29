from __future__ import annotations

from typing import Any, Dict, Optional

from core.llm import LLMClient
from core.models import Contact, ContactRole

_ROLE_LABEL = {
    ContactRole.RECRUITER: "recruiter",
    ContactRole.TALENT_ACQUISITION: "talent acquisition partner",
    ContactRole.HIRING_MANAGER: "hiring manager",
    ContactRole.HR: "people / HR team member",
    ContactRole.UNKNOWN: "team member",
}

_SYSTEM = (
    "You help a job seeker write short, warm, professional cold-outreach messages "
    "to recruiters and hiring contacts. Messages must be genuine and specific, "
    "never pushy or spammy. Always reply with a single JSON object."
)


class OutreachDrafter:
    """Drafts a short, personalised outreach message for a contact.

    Reuses the shared LLMClient (OpenAI-compatible endpoint configured under the
    `llm:` block, same as the Apply Assistant). Falls back to a simple template
    when no LLM is available. The message is for the user to review and send
    manually — nothing is ever sent from here.
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.profile: Dict[str, Any] = config.get("candidate_profile", {})
        self.llm = LLMClient(config)

    def draft(
        self,
        contact: Contact,
        related_job: Optional[Dict[str, Any]] = None,
        cv_text: str = "",
    ) -> str:
        """Return a draft outreach message (LLM-generated or templated fallback)."""
        if self.llm.available:
            msg = self._draft_with_llm(contact, related_job, cv_text)
            if msg:
                return msg
        return self._fallback_template(contact, related_job)

    # ─── LLM ────────────────────────────────────────────────────────────────────

    def _draft_with_llm(
        self, contact: Contact, related_job: Optional[Dict[str, Any]], cv_text: str
    ) -> Optional[str]:
        job_title = (related_job or {}).get("title", "a relevant role")
        first_name = contact.full_name.split()[0] if contact.full_name else "there"
        role_label = _ROLE_LABEL.get(contact.role, "team member")

        user = f"""
Write a cold-outreach message to a {role_label} at {contact.company}.

Candidate:
- Name: {self.profile.get("first_name")} {self.profile.get("last_name")}
- Target role: {job_title} at {contact.company}
- GitHub: {self.profile.get("github_url")}
- LinkedIn: {self.profile.get("linkedin_url")}
- Portfolio: {self.profile.get("portfolio_url")}

Candidate CV summary:
\"\"\"
{cv_text[:1500]}
\"\"\"

Recipient:
- Name: {contact.full_name}
- Title: {contact.title or role_label}

The message must, in under 120 words:
1. Greet {first_name} by first name.
2. Briefly say who the candidate is and why they fit {job_title}.
3. Reference one concrete, relevant strength from the CV.
4. End with a low-pressure ask (a quick chat or a pointer to the right person).
Keep it human and specific. No subject line, no markdown.

Return JSON: {{"message": "<the message>"}}
"""
        data = self.llm.chat_json(_SYSTEM, user)
        if not data:
            return None
        msg = (data.get("message") or "").strip()
        return msg or None

    # ─── Fallback ────────────────────────────────────────────────────────────────

    def _fallback_template(
        self, contact: Contact, related_job: Optional[Dict[str, Any]]
    ) -> str:
        first_name = contact.full_name.split()[0] if contact.full_name else "there"
        job_title = (related_job or {}).get("title", "opportunities on your team")
        me = f"{self.profile.get('first_name', '')} {self.profile.get('last_name', '')}".strip()
        links = " | ".join(
            v
            for v in (
                self.profile.get("portfolio_url"),
                self.profile.get("github_url"),
                self.profile.get("linkedin_url"),
            )
            if v
        )
        return (
            f"Hi {first_name},\n\n"
            f"I'm {me}, a software engineer who's really interested in {job_title} "
            f"at {contact.company}. I've been building full-stack products "
            f"(React, Node.js, .NET) and would love to learn more about your team and "
            f"any openings that might be a fit.\n\n"
            f"Happy to share more — here are a few links: {links}\n\n"
            f"Thanks for your time!\n{me}"
        )
