from __future__ import annotations

"""
apply_assistant.py — ToS-safe application helper
=================================================
Replaces the old auto-submit applier. Instead of automating LinkedIn (which
violates their Terms of Service and risks an account ban), this generates a
tailored cover letter and talking points for each eligible job using a free
OpenAI-compatible LLM. The drafts are stored on the job row and surfaced in the
dashboard so the candidate reviews and applies themselves — a human stays in
the loop.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.database import get_draft_candidates, save_application_draft
from core.llm import LLMClient
from core.models import CVProfile, Job


class ApplyAssistant:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.cfg = config.get("apply_assistant", {})
        self.profile = config.get("candidate_profile", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.policy = self.cfg.get("policy", "both")
        self.min_score = float(self.cfg.get("min_match_score", 75))
        self.max_drafts = int(self.cfg.get("max_drafts_per_run", 10))
        self.skip_unauthorized = bool(self.cfg.get("skip_unauthorized", True))
        self.llm = LLMClient(config)

    def run(self) -> int:
        """Generate and store drafts for eligible jobs. Returns the count drafted."""
        if not self.enabled:
            print("  [ApplyAssistant] Disabled in config.yaml. Skipping.")
            return 0

        if not self.llm.available:
            print(
                "  [ApplyAssistant] No LLM API key found "
                f"(set {self.config.get('llm', {}).get('api_key_env', 'OPENROUTER_API_KEY')}). Skipping."
            )
            return 0

        candidates = get_draft_candidates(self.policy, self.min_score)

        if self.skip_unauthorized:
            candidates = [j for j in candidates if j.work_authorized is not False]

        if not candidates:
            print("  [ApplyAssistant] No jobs need a draft right now.")
            return 0

        candidates = candidates[: self.max_drafts]
        print(f"  [ApplyAssistant] Drafting applications for {len(candidates)} jobs via {self.llm.model} …")

        cv_profiles = self._load_cv_texts()
        drafted = 0

        for idx, job in enumerate(candidates, 1):
            cv_id = job.score.suggested_cv if job.score else "swe"
            cv_profile = cv_profiles.get(cv_id)
            print(f"  [ApplyAssistant] [{idx}/{len(candidates)}] {job.title} @ {job.company}")

            draft = self._generate_draft(job, cv_profile)
            if draft:
                try:
                    save_application_draft(job.id, draft)
                    drafted += 1
                except Exception as exc:
                    print(f"  [ApplyAssistant] ⚠️ Failed to save draft for {job.id}: {exc}")
            else:
                print("  [ApplyAssistant] ⚠️ No draft generated (LLM unavailable or unparseable).")

        print(f"\n  [ApplyAssistant] Done. Generated {drafted} application drafts.")
        return drafted

    # ── Internals ─────────────────────────────────────────────────────────────

    def _load_cv_texts(self) -> Dict[str, CVProfile]:
        from ranking.cv_parser import load_cv_profiles
        try:
            swe, pm = load_cv_profiles()
            return {"swe": swe, "pm": pm}
        except Exception as e:
            print(f"  [ApplyAssistant] ⚠️ Could not load CV profiles: {e}")
            return {}

    def _generate_draft(self, job: Job, cv_profile: Optional[CVProfile]) -> Optional[Dict]:
        cv_text = cv_profile.raw_text if cv_profile else ""
        skills_str = ", ".join(cv_profile.skills) if cv_profile else ""

        system = (
            "You are an expert career assistant helping a candidate apply to software/product "
            "roles. You write concise, honest, specific application material. Never invent "
            "experience the candidate doesn't have, and never use placeholder text like "
            "[Company] — use the real details provided. Always respond with valid JSON only."
        )
        user = f"""
Candidate:
- Name: {self.profile.get("first_name", "")} {self.profile.get("last_name", "")}
- Seniority: {cv_profile.seniority if cv_profile else "entry"} ({cv_profile.years_experience if cv_profile else 0} yrs)
- Skills: {skills_str}
- Portfolio: {self.profile.get("portfolio_url", "")}
- GitHub: {self.profile.get("github_url", "")}

Candidate CV (excerpt):
\"\"\"
{cv_text[:2500]}
\"\"\"

Target job:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or "N/A"}
- Description (excerpt):
\"\"\"
{(job.description or "")[:2000]}
\"\"\"

Produce application material as JSON with exactly these keys:
{{
  "cover_letter": "3 short paragraphs (~160 words total), addressed to the {job.company} hiring team, connecting the candidate's real skills/experience to this specific role. Professional, warm, no clichés, no placeholders.",
  "talking_points": ["3-5 short bullet strings: concrete CV-to-role connections to raise in an interview, plus 1 honest gap the candidate should be ready to address"],
  "fit_summary": "one sentence on why this is (or isn't) a strong fit"
}}
Return ONLY the JSON object.
"""

        data = self.llm.chat_json(system, user)
        if not data or "cover_letter" not in data:
            return None

        # Normalise talking_points to a list of strings.
        tps = data.get("talking_points", [])
        if isinstance(tps, str):
            tps = [tps]
        tps = [str(t).strip() for t in tps if str(t).strip()]

        return {
            "cover_letter": str(data.get("cover_letter", "")).strip(),
            "talking_points": tps,
            "fit_summary": str(data.get("fit_summary", "")).strip(),
            "model": self.llm.model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
