import re
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Public API ────────────────────────────────────────────────────────────────


def parse_posted_date(raw: Optional[str]) -> Optional[datetime]:
    """
    Normalise any human-readable or ISO job-posting date string into a
    timezone-aware UTC datetime.

    Handles formats from LinkedIn, JobStreet, Glints, Indeed and Kalibrr:
      • "2 days ago"           • "Posted 3 hours ago"
      • "Just now"             • "Today"             • "Yesterday"
      • "1 week ago"           • "30+ days ago"
      • "2024-01-15"           • "Jan 15, 2024"      • "15 Jan 2024"
      • "January 15, 2024"     • "15/01/2024"
      • ISO-8601 with offset   • Unix ms timestamps (as strings)
      • Bahasa equivalents     ("hari ini", "kemarin", "menit lalu", etc.)

    Returns None when the string cannot be parsed so callers can decide
    whether to default to now() or leave the field null.
    """
    if not raw:
        return None

    text = raw.strip().lower()
    now = _now()

    # ── Relative: minutes ────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*(?:minute|min|menit)", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    # ── Relative: hours ──────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*(?:hour|hr|jam)", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    # ── Relative: days ───────────────────────────────────────────────────────
    # "30+ days ago" → treat as 30
    m = re.search(r"(\d+)\+?\s*(?:day|hari)", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # ── Relative: weeks ──────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*(?:week|minggu)", text)
    if m:
        return now - timedelta(weeks=int(m.group(1)))

    # ── Relative: months ─────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*(?:month|bulan)", text)
    if m:
        return now - timedelta(days=int(m.group(1)) * 30)

    # ── Anchors: just now / today ────────────────────────────────────────────
    if any(
        tok in text
        for tok in ("just now", "baru saja", "today", "hari ini", "just posted")
    ):
        return now

    # ── Anchors: yesterday ───────────────────────────────────────────────────
    if any(tok in text for tok in ("yesterday", "kemarin")):
        return now - timedelta(days=1)

    # ── Unix timestamp in milliseconds (numeric string) ──────────────────────
    if re.fullmatch(r"\d{13}", text):
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            pass

    # ── Unix timestamp in seconds ────────────────────────────────────────────
    if re.fullmatch(r"\d{10}", text):
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (ValueError, OSError):
            pass

    # ── ISO-8601 with timezone offset (e.g. "2024-01-15T08:30:00+08:00") ────
    try:
        dt = datetime.fromisoformat(raw.strip())
        return _ensure_utc(dt)
    except ValueError:
        pass

    # ── ISO date only: "2024-01-15" ──────────────────────────────────────────
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            dt = datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
            )
            return dt
        except ValueError:
            pass

    # ── DD/MM/YYYY or MM/DD/YYYY ─────────────────────────────────────────────
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Assume DD/MM/YYYY (common in MY/ID)
        try:
            return datetime(year, b, a, tzinfo=timezone.utc)
        except ValueError:
            try:
                return datetime(year, a, b, tzinfo=timezone.utc)
            except ValueError:
                pass

    # ── Named month formats ──────────────────────────────────────────────────
    # "Jan 15, 2024" / "January 15, 2024" / "15 Jan 2024" / "15 January 2024"
    named_formats = [
        "%b %d, %Y",  # Jan 15, 2024
        "%B %d, %Y",  # January 15, 2024
        "%d %b %Y",  # 15 Jan 2024
        "%d %B %Y",  # 15 January 2024
        "%b %d %Y",  # Jan 15 2024
        "%B %d %Y",  # January 15 2024
        "%d-%b-%Y",  # 15-Jan-2024
    ]
    # Use the original (non-lowercased) string for strptime to match month names
    raw_stripped = raw.strip()
    for fmt in named_formats:
        try:
            dt = datetime.strptime(raw_stripped, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Final attempt: strip common prefixes like "Posted on ", "Active since "
    prefixes = ("posted on ", "posted ", "active since ", "listed on ", "date posted: ")
    for prefix in prefixes:
        if text.startswith(prefix):
            cleaned = raw_stripped[len(prefix) :]
            result = parse_posted_date(cleaned)
            if result:
                return result

    return None


def days_since_posted(posted_at: Optional[datetime]) -> Optional[int]:
    """Return the number of whole days between posted_at and now (UTC)."""
    if posted_at is None:
        return None
    posted_at = _ensure_utc(posted_at)
    delta = _now() - posted_at
    return max(0, delta.days)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    """Attach UTC timezone if the datetime is naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
