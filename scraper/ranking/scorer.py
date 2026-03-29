from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import yaml
from core.models import CVProfile, Job, JobScore, MatchLabel
from ranking.embeddings import compute_skills_similarity, title_similarity
from ranking.job_parser import (
    detect_location_type,
    extract_job_skills,
    extract_seniority,
    extract_years_required,
)

# ─── Config loader ────────────────────────────────────────────────────────────


def _load_scoring_config() -> dict:
    scraper_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(scraper_root, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("scoring", {})


# ─── Public API ───────────────────────────────────────────────────────────────


def score_job(
    job: Job,
    swe_profile: CVProfile,
    pm_profile: CVProfile,
) -> JobScore:
    """
    Score a job against both CV profiles and return the best result.

    The scorer:
      1. Runs all four sub-scorers against BOTH CVs.
      2. Picks the CV that yields the higher overall score.
      3. Assigns a MatchLabel (Strong / Decent / Low) based on thresholds.
      4. Sets `suggested_cv` on the returned JobScore.

    Weights (from config.yaml):
      skills    40%  – semantic similarity of CV skills vs. job-required skills
      seniority 25%  – alignment of candidate level with the role's expectations
      recency   20%  – how recently the job was posted
      title     15%  – how closely the job title matches preferred titles

    Args:
        job:         The scraped Job object (must have .title and .description).
        swe_profile: Parsed SWE / developer CV profile.
        pm_profile:  Parsed Product Manager CV profile.

    Returns:
        A JobScore with all sub-scores, an overall score (0–100), a label, and
        the id of the suggested CV ('swe' or 'pm').
    """
    config = _load_scoring_config()
    weights: dict[str, float] = config.get(
        "weights",
        {"skills": 0.40, "seniority": 0.25, "recency": 0.20, "title": 0.15},
    )
    thresholds: dict[str, float] = config.get(
        "thresholds", {"strong": 75.0, "decent": 50.0}
    )

    swe_score = _score_against_profile(job, swe_profile, weights)
    pm_score = _score_against_profile(job, pm_profile, weights)

    # ── Pick the better-matching CV ───────────────────────────────────────────
    if swe_score.overall >= pm_score.overall:
        best = swe_score
        best.suggested_cv = "swe"
    else:
        best = pm_score
        best.suggested_cv = "pm"

    # ── Assign label ──────────────────────────────────────────────────────────
    if best.overall >= thresholds.get("strong", 75):
        best.label = MatchLabel.STRONG
    elif best.overall >= thresholds.get("decent", 50):
        best.label = MatchLabel.DECENT
    else:
        best.label = MatchLabel.LOW

    return best


def score_jobs_bulk(
    jobs: list[Job],
    swe_profile: CVProfile,
    pm_profile: CVProfile,
) -> list[Job]:
    """
    Score a list of jobs in place, attaching a JobScore to each.

    Logs progress to stdout so GitHub Actions shows live output during long
    scrape runs.

    Args:
        jobs:        List of Job objects to score.
        swe_profile: SWE CV profile.
        pm_profile:  PM CV profile.

    Returns:
        The same list of Jobs, each with `.score` populated.
    """
    total = len(jobs)
    for idx, job in enumerate(jobs, start=1):
        try:
            job.score = score_job(job, swe_profile, pm_profile)
            label_symbol = _label_symbol(job.score.label)
            print(
                f"  [{idx:>3}/{total}] {label_symbol} {job.score.overall:5.1f}  "
                f"{job.title[:50]:<50}  @ {job.company[:30]}"
            )
        except Exception as exc:
            # Never let a single scoring failure abort the entire run
            print(f"  [{idx:>3}/{total}] ⚠️  Scoring error for '{job.title}': {exc}")
            job.score = JobScore()  # zero score fallback

    return jobs


# ─── Per-profile scorer ───────────────────────────────────────────────────────


def _score_against_profile(
    job: Job,
    profile: CVProfile,
    weights: dict[str, float],
) -> JobScore:
    """
    Compute the four sub-scores and the weighted overall for one CV profile.
    All sub-scores are in [0, 100].
    """
    title = job.title or ""
    description = job.description or ""

    # ── 1. Skills score ───────────────────────────────────────────────────────
    skills_score = _skills_score(profile, description, title)

    # ── 2. Seniority score ────────────────────────────────────────────────────
    seniority_score = _seniority_score(profile, title, description)

    # ── 3. Recency score ──────────────────────────────────────────────────────
    recency_score = _recency_score(job.posted_at)

    # ── 4. Title score ────────────────────────────────────────────────────────
    title_score = _title_score(title, profile.titles)

    # ── Weighted overall ──────────────────────────────────────────────────────
    overall = (
        skills_score * weights.get("skills", 0.40)
        + seniority_score * weights.get("seniority", 0.25)
        + recency_score * weights.get("recency", 0.20)
        + title_score * weights.get("title", 0.15)
    )
    overall = round(min(max(overall, 0.0), 100.0), 1)

    return JobScore(
        overall=overall,
        skills=round(skills_score, 1),
        seniority=round(seniority_score, 1),
        recency=round(recency_score, 1),
        title=round(title_score, 1),
        # label and suggested_cv are set by the caller
    )


# ─── Sub-scorers ─────────────────────────────────────────────────────────────


def _skills_score(profile: CVProfile, description: str, title: str) -> float:
    """
    Score how well the candidate's skills match the job's requirements.

    Primary method: semantic cosine similarity between the CV skill list and
    the skills extracted from the job description.

    Fallback (when the job description is too short or no skills are extracted):
    keyword overlap count — how many CV skills literally appear in the text.

    The two methods are blended when both are available so that literal matches
    reinforce semantic matches.
    """
    job_skills = extract_job_skills(description)

    # ── Semantic similarity ───────────────────────────────────────────────────
    semantic_score: float = 0.0
    if job_skills and profile.skills:
        raw = compute_skills_similarity(profile.skills, job_skills)
        semantic_score = raw * 100

    # ── Keyword overlap ───────────────────────────────────────────────────────
    overlap_score: float = _keyword_overlap_score(profile.skills, description, title)

    # ── Also compare raw_text / profile context against job description ───────
    context_score: float = 0.0
    if profile.raw_text and description:
        from ranking.embeddings import compute_similarity  # lazy import avoids circular

        raw_ctx = compute_similarity(profile.raw_text[:512], description[:512])
        context_score = raw_ctx * 100

    # ── Blend ─────────────────────────────────────────────────────────────────
    if semantic_score > 0 and context_score > 0:
        # Weighted blend: semantic 50%, keyword overlap 30%, context 20%
        combined = semantic_score * 0.50 + overlap_score * 0.30 + context_score * 0.20
    elif semantic_score > 0:
        combined = semantic_score * 0.70 + overlap_score * 0.30
    else:
        # No skills extracted from job — fall back to pure overlap + context
        combined = overlap_score * 0.60 + context_score * 0.40

    return min(combined, 100.0)


def _keyword_overlap_score(
    cv_skills: list[str],
    description: str,
    title: str,
) -> float:
    """
    Count how many CV skills appear literally in the job description or title.
    Normalised to 100 assuming ~30% of skills are expected to match a typical
    posting (to avoid punishing specialists with a deep but narrow skill set).
    """
    if not cv_skills or (not description and not title):
        return 0.0

    text_lower = f"{description} {title}".lower()
    matches = sum(1 for skill in cv_skills if skill.lower() in text_lower)

    # Normalise: 30% match rate → 100 points
    expected_match_rate = 0.30
    normalised = matches / max(len(cv_skills) * expected_match_rate, 1)
    return min(normalised * 100, 100.0)


def _seniority_score(profile: CVProfile, title: str, description: str) -> float:
    """
    Score the alignment between the candidate's seniority level and what the
    job requires.

    Scoring philosophy:
      • Exact match                    → 100
      • Candidate is slightly over-qualified (one level above) → 75
        (hiring managers often consider over-qualified candidates, especially
        for entry/junior roles where a fresh grad applies to a mid-level post)
      • Candidate is one level under-qualified → 50
        (still worth applying; many postings inflate requirements)
      • Two levels apart               → 15

    Additionally, required years of experience is used as a secondary signal
    to fine-tune the score when the title/description wording is ambiguous.
    """
    _LEVELS: dict[str, int] = {"entry": 0, "mid": 1, "senior": 2}

    job_seniority = extract_seniority(title, description)
    cv_level = _LEVELS.get(profile.seniority, 0)
    job_level = _LEVELS.get(job_seniority, 1)

    diff = cv_level - job_level  # positive → over-qualified, negative → under

    if diff == 0:
        base_score = 100.0
    elif diff == 1:  # slightly over-qualified
        base_score = 75.0
    elif diff == -1:  # slightly under-qualified
        base_score = 50.0
    else:  # 2-level gap either direction
        base_score = 15.0

    # ── Years-of-experience adjustment ───────────────────────────────────────
    years_required = extract_years_required(description)
    if years_required is not None:
        years_score = _years_match_score(profile.years_experience, years_required)
        # Blend: 60% title-based seniority, 40% years-based
        return base_score * 0.60 + years_score * 0.40

    return base_score


def _years_match_score(cv_years: float, required_years: float) -> float:
    """
    Score based on years of experience.

    • cv_years >= required_years → 100 (fully qualified)
    • cv_years == 0, required == 0 → 100 (fresh-grad role, fresh-grad candidate)
    • Linear interpolation below the threshold
    • Being significantly over-qualified (2× the requirement) still scores 100
    """
    if required_years <= 0:
        return 100.0
    if cv_years >= required_years:
        return 100.0

    ratio = cv_years / required_years
    return round(ratio * 100, 1)


def _recency_score(posted_at: Optional[datetime]) -> float:
    """
    Score based on how recently the job was posted.

    A very recent posting means more competition but also a higher chance the
    role is still open — we want to prioritise fresh listings.

    Scale:
      Just posted (< 1h)  → 100
      < 24 hours          → 95
      1–3 days            → 85
      4–7 days            → 70
      8–14 days           → 45
      15–30 days          → 20
      > 30 days           → 0   (too stale — likely filled or re-posted)
      Unknown date        → 55  (neutral — don't penalise, don't reward)
    """
    if posted_at is None:
        return 55.0  # neutral default when date is unavailable

    now = datetime.now(tz=timezone.utc)

    # Ensure timezone-aware comparison
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)

    age_seconds = (now - posted_at).total_seconds()
    age_hours = age_seconds / 3600
    age_days = age_seconds / 86400

    if age_hours < 1:
        return 100.0
    if age_hours < 24:
        return 95.0
    if age_days <= 3:
        return 85.0
    if age_days <= 7:
        return 70.0
    if age_days <= 14:
        return 45.0
    if age_days <= 30:
        return 20.0
    return 0.0


def _title_score(job_title: str, preferred_titles: list[str]) -> float:
    """
    Score how well the job title matches the candidate's preferred titles.

    Two-pass approach:
      1. Exact / substring match → 100 (fast, no model needed)
      2. Semantic similarity via sentence-transformers (handles synonyms /
         paraphrases like "Full-stack Engineer" ≈ "Software Developer")

    The best score from both passes is returned.
    """
    if not job_title or not preferred_titles:
        return 0.0

    job_lower = job_title.lower()

    # ── Pass 1: exact / substring ─────────────────────────────────────────────
    for preferred in preferred_titles:
        pref_lower = preferred.lower()
        if pref_lower in job_lower or job_lower in pref_lower:
            return 100.0

    # ── Pass 2: word-level token overlap ─────────────────────────────────────
    job_tokens = set(re.sub(r"[^\w\s]", "", job_lower).split())
    best_token_score = 0.0
    for preferred in preferred_titles:
        pref_lower = preferred.lower()
        pref_tokens = set(re.sub(r"[^\w\s]", "", pref_lower).split())
        overlap = len(job_tokens & pref_tokens)
        if overlap > 0:
            score = overlap / max(len(pref_tokens), 1) * 80  # max 80 for partial
            best_token_score = max(best_token_score, score)

    # ── Pass 3: semantic similarity ───────────────────────────────────────────
    semantic = title_similarity(job_title, preferred_titles) * 100

    return min(max(best_token_score, semantic), 100.0)


# ─── Utility ─────────────────────────────────────────────────────────────────

import re  # noqa: E402  (placed here to keep top-level imports clean)


def _label_symbol(label: MatchLabel) -> str:
    return {
        MatchLabel.STRONG: "🟢",
        MatchLabel.DECENT: "🟡",
        MatchLabel.LOW: "🔴",
    }.get(label, "⚪")
