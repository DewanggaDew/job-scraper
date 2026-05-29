from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from core.models import (
    Contact,
    ContactRole,
    ContactSource,
    ContactStatus,
    CVProfile,
    EmailStatus,
    Job,
    JobScore,
    JobStatus,
    LocationType,
    MatchLabel,
    ScrapeSummary,
)

from postgrest.exceptions import APIError
from supabase import Client, create_client

# ─── Client ──────────────────────────────────────────────────────────────────


def _execute(request_builder: Any) -> Any:
    """Run PostgREST execute(); map missing-table errors to a setup hint."""
    try:
        return request_builder.execute()
    except APIError as e:
        if e.code == "PGRST205":
            raise RuntimeError(
                "Supabase has no matching table (schema not applied). "
                "Open supabase/schema.sql in this repo, paste it into "
                "Supabase Dashboard → SQL Editor, and run it."
            ) from e
        raise


_client: Optional[Client] = None


def get_client() -> Client:
    """Return a module-level singleton Supabase client (avoids re-creating per call)."""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


# ─── Jobs ────────────────────────────────────────────────────────────────────


def _job_to_row(job: Job) -> Dict[str, Any]:
    """Convert a Job model to a dict suitable for Supabase upsert."""
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
        "work_authorized": job.work_authorized,
        "status": job.status.value,
        "notes": job.notes,
        "applied_at": job.applied_at.isoformat() if job.applied_at else None,
        "auto_apply_error": job.auto_apply_error,
        "auto_apply_attempted_at": job.auto_apply_attempted_at.isoformat() if job.auto_apply_attempted_at else None,
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

    return data


def upsert_job(job: Job) -> None:
    """Insert or update a single job (kept for backward compatibility)."""
    client = get_client()
    _execute(client.table("jobs").upsert(_job_to_row(job), on_conflict="id"))


def upsert_jobs_batch(jobs: List[Job], batch_size: int = 50) -> int:
    """
    Upsert jobs in batches. Returns the number of rows that failed to save.
    PostgREST supports array upserts natively so each batch is one HTTP call.
    """
    client = get_client()
    rows = [_job_to_row(j) for j in jobs]
    errors = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            _execute(client.table("jobs").upsert(batch, on_conflict="id"))
        except Exception as exc:
            errors += len(batch)
            print(f"  ⚠️  Batch upsert failed (rows {i}–{i + len(batch)}): {exc}")

    return errors


def purge_stale_jobs(max_age_days: int = 7) -> int:
    """
    Delete jobs that are both posted 7+ days ago AND scraped 7+ days ago.
    Protects jobs the user has interacted with (status != 'new').
    Returns the number of deleted rows.
    """
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    # A job is stale when ALL three conditions are met:
    #   - scraped_at is older than the cutoff
    #   - posted_at is older than the cutoff (NULL posted_at → keep the job)
    #   - the user hasn't saved / applied / etc.
    stale = _execute(
        client.table("jobs")
        .select("id")
        .eq("status", "new")
        .lt("scraped_at", cutoff)
        .not_.is_("posted_at", "null")
        .lt("posted_at", cutoff)
    )
    stale_rows = stale.data or []

    ids_to_delete = [row["id"] for row in stale_rows]

    if not ids_to_delete:
        return 0

    # Supabase .in_() has a practical limit; batch in chunks of 200.
    deleted = 0
    for i in range(0, len(ids_to_delete), 200):
        batch = ids_to_delete[i : i + 200]
        _execute(client.table("jobs").delete().in_("id", batch))
        deleted += len(batch)

    return deleted


def get_existing_job_ids() -> Set[str]:
    """Return the set of all job IDs already in the database (for deduplication)."""
    client = get_client()
    result = _execute(client.table("jobs").select("id"))
    return {row["id"] for row in (result.data or [])}


def get_new_strong_matches(since: datetime) -> List[Dict[str, Any]]:
    """
    Return Strong (and optionally Decent) matches scraped after *since*.
    Used to decide what to include in the notification email.
    """
    client = get_client()
    result = _execute(
        client.table("jobs")
        .select(
            "id, title, company, location, location_type, source, url, "
            "posted_at, easy_apply, match_score, match_label, suggested_cv"
        )
        .in_("match_label", ["Strong", "Decent"])
        .gte("scraped_at", since.isoformat())
        .order("match_score", desc=True)
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

    _execute(client.table("jobs").update(payload).eq("id", job_id))


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

    result = _execute(query)
    return result.data or []


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    client = get_client()
    result = _execute(client.table("jobs").select("*").eq("id", job_id).single())
    return result.data


def get_dashboard_stats() -> Dict[str, int]:
    """Aggregate counts for the stats bar on the dashboard."""
    client = get_client()

    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    all_jobs = _execute(
        client.table("jobs").select("match_label, status, scraped_at")
    )
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
    _execute(
        client.table("cv_profiles").upsert(
            {
                "id": profile.id,
                "skills": profile.skills,
                "titles": profile.titles,
                "years_experience": profile.years_experience,
                "seniority": profile.seniority,
                "raw_text": profile.raw_text,
            }
        )
    )


def get_cv_profiles() -> Dict[str, Dict[str, Any]]:
    """Return both CV profiles keyed by id ('swe', 'pm')."""
    client = get_client()
    result = _execute(client.table("cv_profiles").select("*"))
    return {row["id"]: row for row in (result.data or [])}


# ─── Scrape Run Audit Log ─────────────────────────────────────────────────────


def log_scrape_run(
    summary: ScrapeSummary,
    email_sent: bool = False,
    error_message: Optional[str] = None,
) -> None:
    client = get_client()
    _execute(
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
        )
    )


# ─── Auto-Apply Helpers ────────────────────────────────────────────────────────


def row_to_job(row: Dict[str, Any]) -> Job:
    """Parse a flat database row back to a structured Job object."""
    posted_at = None
    if row.get("posted_at"):
        posted_at = datetime.fromisoformat(row["posted_at"].replace("Z", "+00:00"))
    
    scraped_at = datetime.fromisoformat(row["scraped_at"].replace("Z", "+00:00"))
    
    applied_at = None
    if row.get("applied_at"):
        applied_at = datetime.fromisoformat(row["applied_at"].replace("Z", "+00:00"))
        
    auto_apply_attempted_at = None
    if row.get("auto_apply_attempted_at"):
        auto_apply_attempted_at = datetime.fromisoformat(row["auto_apply_attempted_at"].replace("Z", "+00:00"))

    score = None
    if row.get("match_score") is not None:
        score = JobScore(
            overall=float(row["match_score"]),
            skills=float(row.get("skills_score") or 0.0),
            seniority=float(row.get("seniority_score") or 0.0),
            recency=float(row.get("recency_score") or 0.0),
            title=float(row.get("title_score") or 0.0),
            label=MatchLabel(row.get("match_label") or "Low"),
            suggested_cv=row.get("suggested_cv") or "swe",
        )

    return Job(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row.get("location"),
        location_type=LocationType(row["location_type"]) if row.get("location_type") else None,
        source=row["source"],
        url=row["url"],
        description=row.get("description"),
        posted_at=posted_at,
        scraped_at=scraped_at,
        easy_apply=bool(row.get("easy_apply")),
        work_authorized=row.get("work_authorized"),
        score=score,
        status=JobStatus(row.get("status") or "new"),
        notes=row.get("notes"),
        applied_at=applied_at,
        auto_apply_error=row.get("auto_apply_error"),
        auto_apply_attempted_at=auto_apply_attempted_at,
    )


def get_queued_jobs() -> List[Job]:
    """Fetch all jobs explicitly queued by the user for auto-apply.

    Restricted to LinkedIn: the AutoApplier only implements the LinkedIn Easy
    Apply flow, and other sources (e.g. JobStreet) also set easy_apply=True but
    use their own application UI that these selectors would never match.
    """
    client = get_client()
    result = _execute(
        client.table("jobs")
        .select("*")
        .eq("status", "queued_apply")
        .eq("easy_apply", True)
        .eq("source", "linkedin")
    )
    return [row_to_job(r) for r in (result.data or [])]


def get_auto_apply_candidates(min_score: float) -> List[Job]:
    """Fetch newly scraped jobs that are strong matches and eligible for auto-apply.

    Restricted to LinkedIn (see get_queued_jobs for why).
    """
    client = get_client()
    result = _execute(
        client.table("jobs")
        .select("*")
        .eq("status", "new")
        .eq("easy_apply", True)
        .eq("source", "linkedin")
        .gte("match_score", min_score)
    )
    return [row_to_job(r) for r in (result.data or [])]


def count_recent_applications(within_hours: int = 24) -> int:
    """Count successful applications submitted within the last *within_hours*.

    Used to enforce a true daily cap across runs (the scraper cron fires every
    4 hours, so a per-run cap alone would allow ~6× the intended daily volume).
    """
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    result = _execute(
        client.table("jobs")
        .select("id", count="exact")
        .eq("status", "applied")
        .gte("applied_at", cutoff)
    )
    return result.count or 0


def get_draft_candidates(policy: str, min_score: float) -> List[Job]:
    """Fetch jobs that should get an Apply-Assistant draft and don't have one yet.

    Unlike auto-apply, drafting is useful for ANY source (it never touches the
    site), so there's no LinkedIn/easy_apply restriction here.
      • policy "manual" → jobs the user queued (status 'queued_apply')
      • policy "auto"   → fresh strong matches (status 'new', score >= min_score)
      • policy "both"   → the union of the two
    """
    client = get_client()
    jobs: List[Job] = []
    seen: Set[str] = set()

    def _add(rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            if r["id"] in seen or r.get("application_draft"):
                continue  # skip duplicates and jobs already drafted
            seen.add(r["id"])
            jobs.append(row_to_job(r))

    if policy in ("manual", "both"):
        res = _execute(client.table("jobs").select("*").eq("status", "queued_apply"))
        _add(res.data or [])

    if policy in ("auto", "both"):
        res = _execute(
            client.table("jobs")
            .select("*")
            .eq("status", "new")
            .gte("match_score", min_score)
            .order("match_score", desc=True)
        )
        _add(res.data or [])

    return jobs


def save_application_draft(job_id: str, draft: Dict[str, Any]) -> None:
    """Persist the Apply-Assistant draft (cover letter + talking points) for a job."""
    client = get_client()
    _execute(client.table("jobs").update({"application_draft": draft}).eq("id", job_id))


def update_auto_apply_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
) -> None:
    """Update the status, attempted timestamp, and error message for a job application."""
    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    
    payload: Dict[str, Any] = {
        "status": status.value,
        "auto_apply_attempted_at": now,
    }
    
    if error is not None:
        payload["auto_apply_error"] = error
    else:
        payload["auto_apply_error"] = None
        
    if status == JobStatus.APPLIED:
        payload["applied_at"] = now

    _execute(client.table("jobs").update(payload).eq("id", job_id))


# ─── Contacts ──────────────────────────────────────────────────────────────────


def _contact_to_row(contact: Contact) -> Dict[str, Any]:
    """Convert a Contact model to a dict suitable for Supabase upsert."""
    return {
        "id": contact.id,
        "company": contact.company,
        "company_domain": contact.company_domain,
        "full_name": contact.full_name,
        "title": contact.title,
        "role": contact.role.value,
        "email": contact.email,
        "email_status": contact.email_status.value,
        "linkedin_url": contact.linkedin_url,
        "source": contact.source.value,
        "confidence": round(contact.confidence, 3),
        "related_job_id": contact.related_job_id,
        "draft_message": contact.draft_message,
        "status": contact.status.value,
        "notes": contact.notes,
        "scraped_at": contact.scraped_at.isoformat(),
    }


def contact_row_to_model(row: Dict[str, Any]) -> Contact:
    """Parse a flat database row back to a structured Contact object."""
    scraped_at = datetime.fromisoformat(row["scraped_at"].replace("Z", "+00:00"))
    return Contact(
        id=row["id"],
        company=row["company"],
        company_domain=row.get("company_domain"),
        full_name=row["full_name"],
        title=row.get("title"),
        role=ContactRole(row.get("role") or "unknown"),
        email=row.get("email"),
        email_status=EmailStatus(row.get("email_status") or "none"),
        linkedin_url=row.get("linkedin_url"),
        source=ContactSource(row["source"]),
        confidence=float(row.get("confidence") or 0.0),
        related_job_id=row.get("related_job_id"),
        draft_message=row.get("draft_message"),
        status=ContactStatus(row.get("status") or "new"),
        notes=row.get("notes"),
        scraped_at=scraped_at,
    )


def get_existing_contact_ids() -> Set[str]:
    """Return the set of all contact IDs already in the database (for deduplication)."""
    client = get_client()
    result = _execute(client.table("contacts").select("id"))
    return {row["id"] for row in (result.data or [])}


def upsert_contacts_batch(contacts: List[Contact], batch_size: int = 50) -> int:
    """Upsert contacts in batches. Returns the number of rows that failed to save."""
    client = get_client()
    rows = [_contact_to_row(c) for c in contacts]
    errors = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            _execute(client.table("contacts").upsert(batch, on_conflict="id"))
        except Exception as exc:
            errors += len(batch)
            print(f"  ⚠️  Contact batch upsert failed (rows {i}–{i + len(batch)}): {exc}")

    return errors


def get_companies_needing_contacts(
    min_score: float,
    statuses: Optional[List[str]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return distinct companies worth chasing that have no contacts yet.

    A company qualifies when it has at least one job that is either a strong/decent
    match (match_score >= *min_score*) OR whose status is in *statuses* (e.g. the
    user saved / queued / applied to it). Companies that already have any contact
    row are excluded so we don't re-process them every run.

    Returns one dict per company: {company, related_job_id, url, company_domain_hint}
    using a representative (highest-scoring) job as the seed.
    """
    client = get_client()

    # Pull candidate jobs (filtered server-side on score; status OR'd in below).
    fields = "id, company, url, source, match_score, status"
    score_rows = _execute(
        client.table("jobs")
        .select(fields)
        .gte("match_score", min_score)
        .order("match_score", desc=True)
    ).data or []

    status_rows: List[Dict[str, Any]] = []
    if statuses:
        status_rows = _execute(
            client.table("jobs").select(fields).in_("status", statuses)
        ).data or []

    # Companies that already have a contact — skip them.
    existing = _execute(client.table("contacts").select("company")).data or []
    companies_with_contacts = {
        (row.get("company") or "").strip().lower() for row in existing
    }

    # Keep the best (highest-scoring) representative job per company.
    best_by_company: Dict[str, Dict[str, Any]] = {}
    for row in score_rows + status_rows:
        company = (row.get("company") or "").strip()
        if not company:
            continue
        key = company.lower()
        if key in companies_with_contacts:
            continue
        prev = best_by_company.get(key)
        if prev is None or (row.get("match_score") or 0) > (prev.get("match_score") or 0):
            best_by_company[key] = row

    results: List[Dict[str, Any]] = []
    for row in best_by_company.values():
        results.append(
            {
                "company": row["company"],
                "related_job_id": row["id"],
                "url": row.get("url"),
                "source": row.get("source"),
            }
        )

    return results[:limit]


def get_contacts(
    *,
    company: Optional[str] = None,
    related_job_id: Optional[str] = None,
    status: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Flexible contact query used by the dashboard."""
    client = get_client()

    query = (
        client.table("contacts")
        .select("*")
        .order("confidence", desc=True)
        .range(offset, offset + limit - 1)
    )

    if company:
        query = query.eq("company", company)
    if related_job_id:
        query = query.eq("related_job_id", related_job_id)
    if status:
        query = query.eq("status", status)
    if role:
        query = query.eq("role", role)

    result = _execute(query)
    return result.data or []


def get_contacts_for_job(job_id: str) -> List[Dict[str, Any]]:
    """Return contacts linked to a specific job."""
    return get_contacts(related_job_id=job_id)


def update_contact_status(contact_id: str, status: ContactStatus) -> None:
    """Update the user-controlled status of a contact."""
    client = get_client()
    _execute(
        client.table("contacts").update({"status": status.value}).eq("id", contact_id)
    )


def update_contact_draft(contact_id: str, draft_message: str) -> None:
    """Update the drafted outreach message for a contact."""
    client = get_client()
    _execute(
        client.table("contacts")
        .update({"draft_message": draft_message})
        .eq("id", contact_id)
    )
