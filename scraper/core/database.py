from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from core.models import CVProfile, Job, JobScore, JobStatus, MatchLabel, ScrapeSummary

from supabase import Client, create_client

# ─── Client ──────────────────────────────────────────────────────────────────


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


# ─── Jobs ────────────────────────────────────────────────────────────────────


def upsert_job(job: Job) -> None:
    """
    Insert a new job or update the score fields if the job already exists.
    We never overwrite status / notes / applied_at — those belong to the user.
    """
    client = get_client()

    data: Dict[str, Any] = {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "location_type": job.location_type.value if job.location_type else None,
        "source": job.source,
        "url": job.url,
        "description": job.description,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "scraped_at": job.scraped_at.isoformat(),
        "easy_apply": job.easy_apply,
    }

    if job.score:
        data.update(
            {
                "match_score": round(job.score.overall, 2),
                "skills_score": round(job.score.skills, 2),
                "seniority_score": round(job.score.seniority, 2),
                "recency_score": round(job.score.recency, 2),
                "title_score": round(job.score.title, 2),
                "match_label": job.score.label.value,
                "suggested_cv": job.score.suggested_cv,
            }
        )

    # upsert — on conflict keep user-controlled columns (status, notes, applied_at)
    # by only updating the columns we explicitly set above.
    (client.table("jobs").upsert(data, on_conflict="id").execute())


def get_existing_job_ids() -> Set[str]:
    """Return the set of all job IDs already in the database (for deduplication)."""
    client = get_client()
    result = client.table("jobs").select("id").execute()
    return {row["id"] for row in (result.data or [])}


def get_new_strong_matches(since: datetime) -> List[Dict[str, Any]]:
    """
    Return Strong (and optionally Decent) matches scraped after *since*.
    Used to decide what to include in the notification email.
    """
    client = get_client()
    result = (
        client.table("jobs")
        .select(
            "id, title, company, location, location_type, source, url, "
            "posted_at, easy_apply, match_score, match_label, suggested_cv"
        )
        .in_("match_label", ["Strong", "Decent"])
        .gte("scraped_at", since.isoformat())
        .order("match_score", desc=True)
        .execute()
    )
    return result.data or []


def update_job_status(
    job_id: str,
    status: JobStatus,
    notes: Optional[str] = None,
    applied_at: Optional[datetime] = None,
) -> None:
    """Update the user-controlled tracking fields for a job."""
    client = get_client()

    payload: Dict[str, Any] = {"status": status.value}
    if notes is not None:
        payload["notes"] = notes
    if applied_at is not None:
        payload["applied_at"] = applied_at.isoformat()

    client.table("jobs").update(payload).eq("id", job_id).execute()


def get_jobs(
    *,
    source: Optional[str] = None,
    match_label: Optional[str] = None,
    status: Optional[str] = None,
    location_type: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Flexible job query used by the dashboard API routes."""
    client = get_client()

    query = (
        client.table("jobs")
        .select("*")
        .order("match_score", desc=True)
        .range(offset, offset + limit - 1)
    )

    if source:
        query = query.eq("source", source)
    if match_label:
        query = query.eq("match_label", match_label)
    if status:
        query = query.eq("status", status)
    if location_type:
        query = query.eq("location_type", location_type)
    if min_score is not None:
        query = query.gte("match_score", min_score)

    result = query.execute()
    return result.data or []


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    client = get_client()
    result = client.table("jobs").select("*").eq("id", job_id).single().execute()
    return result.data


def get_dashboard_stats() -> Dict[str, int]:
    """Aggregate counts for the stats bar on the dashboard."""
    client = get_client()

    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    all_jobs = client.table("jobs").select("match_label, status, scraped_at").execute()
    rows = all_jobs.data or []

    stats: Dict[str, int] = {
        "total": len(rows),
        "strong": 0,
        "decent": 0,
        "low": 0,
        "new_today": 0,
        "applied": 0,
        "interviewing": 0,
    }

    for row in rows:
        label = row.get("match_label")
        if label == "Strong":
            stats["strong"] += 1
        elif label == "Decent":
            stats["decent"] += 1
        elif label == "Low":
            stats["low"] += 1

        if row.get("status") == "applied":
            stats["applied"] += 1
        elif row.get("status") == "interviewing":
            stats["interviewing"] += 1

        scraped = row.get("scraped_at", "")
        if scraped and scraped >= today_start:
            stats["new_today"] += 1

    return stats


# ─── CV Profiles ─────────────────────────────────────────────────────────────


def upsert_cv_profile(profile: CVProfile) -> None:
    client = get_client()
    client.table("cv_profiles").upsert(
        {
            "id": profile.id,
            "skills": profile.skills,
            "titles": profile.titles,
            "years_experience": profile.years_experience,
            "seniority": profile.seniority,
            "raw_text": profile.raw_text,
        }
    ).execute()


def get_cv_profiles() -> Dict[str, Dict[str, Any]]:
    """Return both CV profiles keyed by id ('swe', 'pm')."""
    client = get_client()
    result = client.table("cv_profiles").select("*").execute()
    return {row["id"]: row for row in (result.data or [])}


# ─── Scrape Run Audit Log ─────────────────────────────────────────────────────


def log_scrape_run(
    summary: ScrapeSummary,
    email_sent: bool = False,
    error_message: Optional[str] = None,
) -> None:
    client = get_client()
    client.table("scrape_runs").insert(
        {
            "started_at": summary.run_at.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "jobs_found": summary.total_scraped,
            "jobs_new": summary.new_jobs,
            "strong_matches": summary.strong_matches,
            "email_sent": email_sent,
            "error_message": error_message
            or ("; ".join(summary.errors) if summary.errors else None),
        }
    ).execute()
