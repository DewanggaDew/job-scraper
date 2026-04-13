from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import yaml
from core.models import CVProfile, Job, JobScore, MatchLabel
from ranking.embeddings import (
    EmbeddingCache,
    compute_skills_similarity,
    title_similarity,
)
from ranking.job_parser import (
    detect_location_type,
    extract_job_skills,
    extract_seniority,
    extract_years_required,
)

# ─── Config loader (cached) ──────────────────────────────────────────────────

_scoring_config: Optional[dict] = None


def _load_scoring_config() -> dict:
    global _scoring_config
    if _scoring_config is None:
        scraper_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(scraper_root, "config.yaml")
        with open(config_path, "r", encoding="utf-8") as fh:
            _scoring_config = yaml.safe_load(fh).get("scoring", {})
    return _scoring_config


# ─── Public API ───────────────────────────────────────────────────────────────


def score_job(
    job: Job,
    swe_profile: CVProfile,
    pm_profile: CVProfile,
    cache: Optional[EmbeddingCache] = None,
) -> JobScore:
    """
    Score a job against both CV profiles and return the best result.

    When *cache* is provided, embedding lookups are resolved from pre-computed
    vectors instead of calling model.encode() per job.
    """
    config = _load_scoring_config()
    weights: dict[str, float] = config.get(
        "weights",
        {"skills": 0.40, "seniority": 0.25, "recency": 0.20, "title": 0.15},
    )
    thresholds: dict[str, float] = config.get(
        "thresholds", {"strong": 75.0, "decent": 50.0}
    )

    swe_score = _score_against_profile(job, swe_profile, weights, cache)
    pm_score = _score_against_profile(job, pm_profile, weights, cache)

    if swe_score.overall >= pm_score.overall:
        best = swe_score
        best.suggested_cv = "swe"
    else:
        best = pm_score
        best.suggested_cv = "pm"

    if best.overall >= thresholds.get("strong", 75):
        best.label = MatchLabel.STRONG
    elif best.overall >= thresholds.get("decent", 50):
        best.label = MatchLabel.DECENT
    else:
        best.label = MatchLabel.LOW

    return best


def _collect_texts_for_batch(
    jobs: list[Job],
    profiles: list[CVProfile],
) -> list[str]:
    """
    Gather every text string that will need an embedding during scoring,
    so we can encode them all in one batch before the scoring loop.
    """
    texts: list[str] = []

    for p in profiles:
        if p.skills:
            texts.append(", ".join(p.skills))
        if p.raw_text:
            texts.append(p.raw_text[:512])
        texts.extend(p.titles)

    for job in jobs:
        title = job.title or ""
        description = job.description or ""

        if title:
            texts.append(title)
        if description:
            texts.append(description[:512])

        job_skills = extract_job_skills(description)
        if job_skills:
            texts.append(", ".join(job_skills))

    return texts


def score_jobs_bulk(
    jobs: list[Job],
    swe_profile: CVProfile,
    pm_profile: CVProfile,
) -> list[Job]:
    """
    Score a list of jobs in place, attaching a JobScore to each.

    Pre-computes all embeddings in a single batch encode call, then scores
    each job using cached vector lookups (no per-job model.encode()).
    """
    print("  Collecting texts for batch encoding …")
    all_texts = _collect_texts_for_batch(jobs, [swe_profile, pm_profile])
    cache = EmbeddingCache()
    cache.warm(all_texts)
    print(f"  ✅  Embedding cache warmed: {cache.size} vectors")

    total = len(jobs)
    for idx, job in enumerate(jobs, start=1):
        try:
            job.score = score_job(job, swe_profile, pm_profile, cache=cache)
            label_symbol = _label_symbol(job.score.label)
            print(
                f"  [{idx:>3}/{total}] {label_symbol} {job.score.overall:5.1f}  "
                f"{job.title[:50]:<50}  @ {job.company[:30]}"
            )
        except Exception as exc:
            print(f"  [{idx:>3}/{total}] ⚠️  Scoring error for '{job.title}': {exc}")
            job.score = JobScore()

    return jobs


# ─── Per-profile scorer ───────────────────────────────────────────────────────


def _score_against_profile(
    job: Job,
    profile: CVProfile,
    weights: dict[str, float],
    cache: Optional[EmbeddingCache] = None,
) -> JobScore:
    """
    Compute the four sub-scores and the weighted overall for one CV profile.
    All sub-scores are in [0, 100].
    """
    title = job.title or ""
    description = job.description or ""

    skills_score = _skills_score(profile, description, title, cache)
    seniority_score = _seniority_score(profile, title, description)
    recency_score = _recency_score(job.posted_at)
    title_score = _title_score(title, profile.titles, cache)

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
    )


# ─── Sub-scorers ─────────────────────────────────────────────────────────────


def _skills_score(
    profile: CVProfile,
    description: str,
    title: str,
    cache: Optional[EmbeddingCache] = None,
) -> float:
    """
    Score how well the candidate's skills match the job's requirements.

    When *cache* is provided, uses pre-computed vectors for cosine lookups
    instead of calling model.encode() per pair.
    """
    job_skills = extract_job_skills(description)

    semantic_score: float = 0.0
    if job_skills and profile.skills:
        cv_text = ", ".join(profile.skills)
        job_text = ", ".join(job_skills)
        if cache:
            semantic_score = cache.cosine(cv_text, job_text) * 100
        else:
            raw = compute_skills_similarity(profile.skills, job_skills)
            semantic_score = raw * 100

    overlap_score: float = _keyword_overlap_score(profile.skills, description, title)

    context_score: float = 0.0
    if profile.raw_text and description:
        cv_ctx = profile.raw_text[:512]
        desc_ctx = description[:512]
        if cache:
            context_score = cache.cosine(cv_ctx, desc_ctx) * 100
        else:
            from ranking.embeddings import compute_similarity
            context_score = compute_similarity(cv_ctx, desc_ctx) * 100

    if semantic_score > 0 and context_score > 0:
        combined = semantic_score * 0.50 + overlap_score * 0.30 + context_score * 0.20
    elif semantic_score > 0:
        combined = semantic_score * 0.70 + overlap_score * 0.30
    else:
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


def _title_score(
    job_title: str,
    preferred_titles: list[str],
    cache: Optional[EmbeddingCache] = None,
) -> float:
    """
    Score how well the job title matches the candidate's preferred titles.

    Three-pass approach:
      1. Exact / substring match -> 100
      2. Word-level token overlap -> max 80
      3. Semantic similarity via embeddings (cached or live)
    """
    if not job_title or not preferred_titles:
        return 0.0

    job_lower = job_title.lower()

    for preferred in preferred_titles:
        pref_lower = preferred.lower()
        if pref_lower in job_lower or job_lower in pref_lower:
            return 100.0

    job_tokens = set(re.sub(r"[^\w\s]", "", job_lower).split())
    best_token_score = 0.0
    for preferred in preferred_titles:
        pref_lower = preferred.lower()
        pref_tokens = set(re.sub(r"[^\w\s]", "", pref_lower).split())
        overlap = len(job_tokens & pref_tokens)
        if overlap > 0:
            score = overlap / max(len(pref_tokens), 1) * 80
            best_token_score = max(best_token_score, score)

    if cache:
        semantic = cache.best_cosine(job_title, preferred_titles) * 100
    else:
        semantic = title_similarity(job_title, preferred_titles) * 100

    return min(max(best_token_score, semantic), 100.0)


def _label_symbol(label: MatchLabel) -> str:
    return {
        MatchLabel.STRONG: "🟢",
        MatchLabel.DECENT: "🟡",
        MatchLabel.LOW: "🔴",
    }.get(label, "⚪")
