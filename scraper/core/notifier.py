from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import resend  # pip install resend

# ─── Public entry point ───────────────────────────────────────────────────────


def send_match_notification(
    jobs: list[dict[str, Any]],
    run_time: datetime | None = None,
) -> bool:
    """
    Send an HTML email summarising new strong (and optionally decent) matches.

    Args:
        jobs:      List of job dicts straight from Supabase (already filtered to
                   the matches worth notifying about).
        run_time:  UTC datetime of this scrape run (defaults to now).

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not jobs:
        return False

    api_key = os.environ.get("RESEND_API_KEY", "")
    to_email = os.environ.get("NOTIFY_EMAIL", "")
    dashboard_url = os.environ.get("DASHBOARD_URL", "#")

    if not api_key or not to_email:
        print("⚠️  Notifier: RESEND_API_KEY or NOTIFY_EMAIL not set — skipping email.")
        return False

    resend.api_key = api_key
    run_time = run_time or datetime.now(timezone.utc)

    strong = [j for j in jobs if j.get("match_label") == "Strong"]
    decent = [j for j in jobs if j.get("match_label") == "Decent"]

    subject = _build_subject(strong, decent)
    html = _build_html(strong, decent, dashboard_url, run_time)

    try:
        resend.Emails.send(
            {
                "from": "Job Scraper <notifications@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html,
            }
        )
        print(
            f"✅  Email sent → {to_email}  ({len(strong)} strong, {len(decent)} decent)"
        )
        return True
    except Exception as exc:
        print(f"❌  Resend error: {exc}")
        return False


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _build_subject(strong: list[dict], decent: list[dict]) -> str:
    parts: list[str] = []
    if strong:
        parts.append(f"🟢 {len(strong)} Strong")
    if decent:
        parts.append(f"🟡 {len(decent)} Decent")
    label = " · ".join(parts) if parts else "New"
    return f"{label} Job Match{'es' if (len(strong) + len(decent)) != 1 else ''} Found"


def _time_ago(iso: str | None) -> str:
    """Convert an ISO timestamp to a human-readable '2h ago' string."""
    if not iso:
        return "Unknown date"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 1:
            return "Just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days}d ago"
        return dt.strftime("%-d %b %Y")
    except Exception:
        return iso[:10]


def _cv_label(cv: str | None) -> str:
    return "SWE / Dev CV" if cv == "swe" else "PM CV" if cv == "pm" else "—"


def _source_label(source: str | None) -> str:
    labels = {
        "linkedin": "LinkedIn",
        "jobstreet": "JobStreet",
        "glints": "Glints",
        "indeed": "Indeed",
        "kalibrr": "Kalibrr",
    }
    return labels.get(source or "", source or "")


def _location_type_label(lt: str | None) -> str:
    labels = {
        "remote": "🌐 Remote",
        "hybrid": "🏠 Hybrid",
        "on-site": "🏢 On-site",
    }
    return labels.get(lt or "", lt or "")


# ─── HTML builders ───────────────────────────────────────────────────────────

_CARD_COLORS = {
    "Strong": {
        "border": "#16a34a",
        "header_bg": "#f0fdf4",
        "badge_bg": "#dcfce7",
        "badge_text": "#15803d",
        "score_bar": "#16a34a",
        "emoji": "🟢",
    },
    "Decent": {
        "border": "#ca8a04",
        "header_bg": "#fefce8",
        "badge_bg": "#fef9c3",
        "badge_text": "#854d0e",
        "score_bar": "#eab308",
        "emoji": "🟡",
    },
}


def _score_bar_html(label: str, score: float | None) -> str:
    """Render a mini labelled progress bar for one score dimension."""
    if score is None:
        return ""
    pct = min(max(round(score), 0), 100)
    colors = _CARD_COLORS.get(label, _CARD_COLORS["Decent"])
    bar_color = colors["score_bar"]
    return f"""
      <tr>
        <td style="padding:2px 8px 2px 0; font-size:11px; color:#6b7280; white-space:nowrap; width:80px;">{label}</td>
        <td style="padding:2px 0;">
          <div style="background:#e5e7eb; border-radius:4px; height:8px; width:160px; overflow:hidden;">
            <div style="background:{bar_color}; height:8px; width:{pct}%;"></div>
          </div>
        </td>
        <td style="padding:2px 0 2px 6px; font-size:11px; color:#374151; font-weight:600;">{pct}</td>
      </tr>"""


def _job_card_html(job: dict[str, Any]) -> str:
    match_label: str = job.get("match_label") or "Decent"
    colors = _CARD_COLORS.get(match_label, _CARD_COLORS["Decent"])

    score = job.get("match_score") or 0
    emoji = colors["emoji"]
    title = job.get("title", "Untitled")
    company = job.get("company", "Unknown Company")
    location = job.get("location") or "Location not specified"
    loc_type = _location_type_label(job.get("location_type"))
    source = _source_label(job.get("source"))
    posted = _time_ago(job.get("posted_at"))
    url = job.get("url", "#")
    easy_apply = job.get("easy_apply", False)
    suggested_cv = _cv_label(job.get("suggested_cv"))

    easy_apply_badge = (
        '<span style="display:inline-block; background:#dbeafe; color:#1d4ed8; '
        "font-size:10px; font-weight:600; padding:1px 6px; border-radius:9999px; "
        'margin-left:6px;">⚡ Easy Apply</span>'
        if easy_apply
        else ""
    )

    score_breakdown = ""
    dimensions = [
        ("Skills", job.get("skills_score")),
        ("Seniority", job.get("seniority_score")),
        ("Recency", job.get("recency_score")),
        ("Title", job.get("title_score")),
    ]
    rows = "".join(
        _score_bar_html(dim, val) for dim, val in dimensions if val is not None
    )
    if rows:
        score_breakdown = f"""
        <table style="border-collapse:collapse; margin-top:10px;" cellspacing="0" cellpadding="0">
          {rows}
        </table>"""

    return f"""
  <div style="border:1.5px solid {colors["border"]}; border-radius:10px; margin-bottom:14px; overflow:hidden; font-family:Arial,sans-serif;">
    <!-- Card header -->
    <div style="background:{colors["header_bg"]}; padding:12px 16px; border-bottom:1px solid {colors["border"]};">
      <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px;">
        <span style="font-size:18px; font-weight:700; color:#111827;">
          {emoji} {round(score)}/100
        </span>
        <span style="background:{colors["badge_bg"]}; color:{colors["badge_text"]};
                     font-size:11px; font-weight:700; padding:2px 10px;
                     border-radius:9999px; text-transform:uppercase; letter-spacing:.5px;">
          {match_label} Match
        </span>
      </div>
      <div style="margin-top:6px; font-size:16px; font-weight:600; color:#1f2937;">
        {title}
        <span style="font-weight:400; color:#4b5563;">@ {company}</span>
      </div>
    </div>

    <!-- Card body -->
    <div style="padding:12px 16px; background:#ffffff;">
      <div style="font-size:13px; color:#374151; line-height:1.7;">
        <div>📍 {loc_type} &nbsp;·&nbsp; {location}</div>
        <div>🕐 {posted} &nbsp;·&nbsp; {source} {easy_apply_badge}</div>
        <div>📄 Suggested CV: <strong>{suggested_cv}</strong></div>
      </div>

      {score_breakdown}

      <div style="margin-top:14px;">
        <a href="{url}"
           style="display:inline-block; padding:9px 20px; background:#16a34a;
                  color:#ffffff; font-size:13px; font-weight:600; text-decoration:none;
                  border-radius:7px;">
          👉 View &amp; Apply
        </a>
      </div>
    </div>
  </div>"""


def _section_html(heading: str, jobs: list[dict], max_jobs: int = 10) -> str:
    if not jobs:
        return ""
    cards = "".join(_job_card_html(j) for j in jobs[:max_jobs])
    overflow = len(jobs) - max_jobs
    overflow_note = (
        f'<p style="color:#6b7280; font-size:12px; margin-top:4px;">'
        f"  + {overflow} more — see dashboard for full list."
        f"</p>"
        if overflow > 0
        else ""
    )
    return f"""
  <h2 style="font-size:17px; font-weight:700; color:#111827; margin:24px 0 12px;">{heading}</h2>
  {cards}
  {overflow_note}"""


def _build_html(
    strong: list[dict],
    decent: list[dict],
    dashboard_url: str,
    run_time: datetime,
) -> str:
    strong_section = _section_html(
        f"🟢 Strong Matches ({len(strong)})", strong, max_jobs=10
    )
    decent_section = _section_html(
        f"🟡 Decent Matches ({len(decent)})", decent, max_jobs=5
    )
    total = len(strong) + len(decent)
    run_str = run_time.strftime("%d %b %Y, %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>New Job Matches</title>
</head>
<body style="margin:0; padding:0; background:#f3f4f6; font-family:Arial,sans-serif;">

  <table width="100%" cellspacing="0" cellpadding="0" style="background:#f3f4f6;">
    <tr>
      <td align="center" style="padding:32px 16px;">

        <!-- Outer card -->
        <table width="600" cellspacing="0" cellpadding="0"
               style="background:#ffffff; border-radius:12px; overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,.08);">

          <!-- ── Header ── -->
          <tr>
            <td style="background:#16a34a; padding:24px 28px;">
              <div style="font-size:22px; font-weight:700; color:#ffffff;">🎯 Job Scraper</div>
              <div style="font-size:14px; color:#bbf7d0; margin-top:4px;">
                {total} new match{"es" if total != 1 else ""} found &nbsp;·&nbsp; {run_str}
              </div>
            </td>
          </tr>

          <!-- ── Body ── -->
          <tr>
            <td style="padding:24px 28px;">
              {strong_section}
              {decent_section}

              <!-- Dashboard CTA -->
              <div style="margin-top:28px; padding:18px 20px; background:#f0fdf4;
                          border:1px solid #bbf7d0; border-radius:10px; text-align:center;">
                <div style="font-size:14px; color:#166534; margin-bottom:10px;">
                  View all jobs, update application status &amp; track your pipeline
                </div>
                <a href="{dashboard_url}"
                   style="display:inline-block; padding:10px 28px; background:#16a34a;
                          color:#ffffff; font-size:14px; font-weight:600;
                          text-decoration:none; border-radius:8px;">
                  Open Dashboard →
                </a>
              </div>
            </td>
          </tr>

          <!-- ── Footer ── -->
          <tr>
            <td style="padding:16px 28px; background:#f9fafb;
                       border-top:1px solid #e5e7eb; text-align:center;">
              <div style="font-size:11px; color:#9ca3af;">
                Sent automatically by your Job Scraper · Running on GitHub Actions every 4 hours
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""
