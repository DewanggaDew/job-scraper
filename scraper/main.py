from __future__ import annotations

# Load .env file for local development (no-op in GitHub Actions where secrets
# are injected as real environment variables)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

"""
main.py — Job Scraper Orchestrator
====================================
Entry point executed by the GitHub Actions cron job every 4 hours.

Run from the scraper/ directory:
    python main.py

Environment variables required (set as GitHub Secrets):
    SUPABASE_URL          Supabase project URL
    SUPABASE_KEY          Supabase service-role key
    RESEND_API_KEY        Resend API key for email notifications
    NOTIFY_EMAIL          Email address to send match alerts to
    LINKEDIN_EMAIL        LinkedIn account email
    LINKEDIN_PASSWORD     LinkedIn account password
    LINKEDIN_COOKIES      (optional) JSON-serialised Playwright session cookies
    DASHBOARD_URL         (optional) URL of the deployed Vercel dashboard
"""

import os
import sys
import traceback
from datetime import datetime, timezone

import yaml
from core.database import (
    get_existing_job_ids,
    get_new_strong_matches,
    log_scrape_run,
    upsert_cv_profile,
    upsert_job,
)
from core.deduplicator import is_duplicate
from core.models import Job, ScrapeSummary
from core.notifier import send_match_notification
from ranking.cv_parser import load_cv_profiles
from ranking.scorer import score_jobs_bulk
from scrapers.glints import GlintsScraper
from scrapers.indeed import IndeedScraper
from scrapers.jobstreet import JobStreetScraper
from scrapers.kalibrr import KalibrrScraper
from scrapers.linkedin import LinkedInScraper

# ─── Config ───────────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load config.yaml from the scraper root directory."""
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.yaml"
    )
    if not os.path.exists(config_path):
        print(f"❌  config.yaml not found at {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ─── Scraper registry ─────────────────────────────────────────────────────────


def build_scrapers(config: dict) -> list:
    """
    Instantiate all enabled scrapers.

    Scrapers are ordered by reliability and data quality:
        1. LinkedIn     — highest volume + Easy Apply flag
        2. JobStreet    — dominant MY/ID board
        3. Glints       — strong SEA coverage, good for remote roles
        4. Indeed       — broad coverage, useful fallback
        5. Kalibrr      — Indonesia-focused, strong for Jakarta tech roles
    """
    return [
        LinkedInScraper(config),
        JobStreetScraper(config),
        GlintsScraper(config),
        IndeedScraper(config),
        KalibrrScraper(config),
    ]


# ─── Main pipeline ────────────────────────────────────────────────────────────


def run() -> None:
    run_start = datetime.now(tz=timezone.utc)
    summary = ScrapeSummary(run_at=run_start)

    print("=" * 65)
    print(f"  🚀  Job Scraper  —  {run_start.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 65)

    # ── Step 1: Load config ───────────────────────────────────────────────────
    print("\n📄  Loading config …")
    config = load_config()
    scoring_cfg = config.get("scoring", {})
    notify_threshold: float = float(scoring_cfg.get("notify_threshold", 75))
    send_decent: bool = bool(
        config.get("notification", {}).get("send_decent_matches", True)
    )

    # ── Step 2: Parse CV profiles ─────────────────────────────────────────────
    print("\n📋  Parsing CV profiles …")
    try:
        swe_profile, pm_profile = load_cv_profiles()
        print(
            f"  SWE CV  — {len(swe_profile.skills)} skills, "
            f"seniority: {swe_profile.seniority}, "
            f"years: {swe_profile.years_experience}"
        )
        print(
            f"  PM  CV  — {len(pm_profile.skills)} skills, "
            f"seniority: {pm_profile.seniority}, "
            f"years: {pm_profile.years_experience}"
        )
        # Persist parsed profiles so the dashboard can inspect them
        upsert_cv_profile(swe_profile)
        upsert_cv_profile(pm_profile)
    except Exception as exc:
        print(f"❌  CV profile loading failed: {exc}")
        summary.add_error("cv_parser", str(exc))
        traceback.print_exc()
        sys.exit(1)

    # ── Step 3: Fetch existing job IDs for deduplication ──────────────────────
    print("\n🗄️   Fetching existing job IDs from Supabase …")
    try:
        existing_ids = get_existing_job_ids()
        print(f"  {len(existing_ids)} jobs already in database.")
    except Exception as exc:
        print(f"❌  Could not connect to Supabase: {exc}")
        summary.add_error("database", str(exc))
        traceback.print_exc()
        sys.exit(1)

    # ── Step 4: Run all scrapers ───────────────────────────────────────────────
    print("\n🔍  Running scrapers …")
    scrapers = build_scrapers(config)
    all_scraped_jobs: list[Job] = []

    for scraper in scrapers:
        source = scraper.source_name
        print(f"\n  ── {source.capitalize()} {'─' * (50 - len(source))}")
        try:
            jobs = scraper.scrape()
            print(f"  ✅  {source.capitalize()}: {len(jobs)} jobs scraped")
            all_scraped_jobs.extend(jobs)
            summary.total_scraped += len(jobs)
        except Exception as exc:
            msg = f"Scraper '{source}' failed: {exc}"
            print(f"  ❌  {msg}")
            summary.add_error(source, str(exc))
            traceback.print_exc()
            # Never let one scraper failure abort the whole run

    print(f"\n  Total scraped (before dedup): {len(all_scraped_jobs)}")

    # ── Step 5: Deduplicate ───────────────────────────────────────────────────
    print("\n🔁  Deduplicating …")
    new_jobs: list[Job] = []
    seen_this_run: set[str] = set()

    for job in all_scraped_jobs:
        if job.id in seen_this_run:
            summary.duplicates_skipped += 1
            continue
        seen_this_run.add(job.id)

        if is_duplicate(job.id, existing_ids):
            summary.duplicates_skipped += 1
            continue

        new_jobs.append(job)

    summary.new_jobs = len(new_jobs)
    print(
        f"  {len(new_jobs)} new jobs  |  "
        f"{summary.duplicates_skipped} duplicates skipped"
    )

    if not new_jobs:
        print("\n  ℹ️   No new jobs to score or save — run complete.")
        _finish(summary, email_sent=False)
        return

    # ── Step 6: Score new jobs ────────────────────────────────────────────────
    print(f"\n🏆  Scoring {len(new_jobs)} new jobs …")
    try:
        scored_jobs = score_jobs_bulk(new_jobs, swe_profile, pm_profile)
    except Exception as exc:
        print(f"❌  Scoring pipeline error: {exc}")
        summary.add_error("scorer", str(exc))
        traceback.print_exc()
        # Fall through — save jobs with no scores rather than losing them
        scored_jobs = new_jobs

    # Tally by label
    for job in scored_jobs:
        if job.score:
            label = job.score.label.value
            if label == "Strong":
                summary.strong_matches += 1
            elif label == "Decent":
                summary.decent_matches += 1
            else:
                summary.low_matches += 1

    print(
        f"\n  Score summary:"
        f"  🟢 Strong: {summary.strong_matches}"
        f"  🟡 Decent: {summary.decent_matches}"
        f"  🔴 Low:    {summary.low_matches}"
    )

    # ── Step 7: Save to Supabase ──────────────────────────────────────────────
    print(f"\n💾  Saving {len(scored_jobs)} jobs to Supabase …")
    save_errors = 0
    for job in scored_jobs:
        try:
            upsert_job(job)
        except Exception as exc:
            save_errors += 1
            if save_errors <= 5:  # don't spam logs for bulk failures
                print(f"  ⚠️  Save error for '{job.title}' @ '{job.company}': {exc}")

    saved_count = len(scored_jobs) - save_errors
    print(f"  ✅  {saved_count} saved  |  {save_errors} failed")

    if save_errors:
        summary.add_error(
            "database",
            f"{save_errors} job(s) failed to save — check Supabase connection.",
        )

    # ── Step 8: Send email notification ──────────────────────────────────────
    print("\n📧  Checking for jobs to notify about …")
    email_sent = False

    try:
        # Fetch the newly saved matches from DB (uses the same cutoff timestamp
        # as this run so we only notify about THIS run's results, never resending)
        notify_jobs = get_new_strong_matches(since=run_start)

        # Filter: only notify if score meets the threshold
        notify_jobs = [
            j for j in notify_jobs if j.get("match_score", 0) >= notify_threshold
        ]

        # Optionally include decent matches
        if not send_decent:
            notify_jobs = [j for j in notify_jobs if j.get("match_label") == "Strong"]

        if notify_jobs:
            print(f"  Sending email for {len(notify_jobs)} matches …")
            email_sent = send_match_notification(notify_jobs, run_time=run_start)
        else:
            print("  No matches above notification threshold — skipping email.")

    except Exception as exc:
        print(f"  ❌  Notification error: {exc}")
        summary.add_error("notifier", str(exc))
        traceback.print_exc()

    # ── Step 9: Log run to audit table ────────────────────────────────────────
    _finish(summary, email_sent=email_sent)


# ─── Finish / summary ─────────────────────────────────────────────────────────


def _finish(summary: ScrapeSummary, email_sent: bool) -> None:
    """Log the run summary to Supabase and print the final report."""
    elapsed = (datetime.now(tz=timezone.utc) - summary.run_at).total_seconds()

    print("\n" + "=" * 65)
    print("  📊  Run Summary")
    print("=" * 65)
    print(f"  Total scraped   : {summary.total_scraped}")
    print(f"  New jobs        : {summary.new_jobs}")
    print(f"  Duplicates      : {summary.duplicates_skipped}")
    print(f"  Strong matches  : {summary.strong_matches}")
    print(f"  Decent matches  : {summary.decent_matches}")
    print(f"  Low matches     : {summary.low_matches}")
    print(f"  Email sent      : {'Yes ✅' if email_sent else 'No'}")
    print(f"  Errors          : {len(summary.errors)}")
    for err in summary.errors:
        print(f"    ⚠️  {err}")
    print(f"  Elapsed         : {elapsed:.1f}s")
    print("=" * 65)

    try:
        log_scrape_run(
            summary=summary,
            email_sent=email_sent,
            error_message="; ".join(summary.errors) if summary.errors else None,
        )
        print("  ✅  Run logged to Supabase.")
    except Exception as exc:
        print(f"  ⚠️  Could not log run to Supabase: {exc}")

    # Exit with non-zero code if there were errors so GitHub Actions marks
    # the workflow as failed and notifies the user
    if summary.errors:
        sys.exit(1)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()
