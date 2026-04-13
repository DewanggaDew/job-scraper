from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class LocationType(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on-site"


class JobStatus(str, Enum):
    NEW = "new"
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"


class MatchLabel(str, Enum):
    STRONG = "Strong"
    DECENT = "Decent"
    LOW = "Low"


class JobScore(BaseModel):
    overall: float = 0.0
    skills: float = 0.0
    seniority: float = 0.0
    recency: float = 0.0
    title: float = 0.0
    label: MatchLabel = MatchLabel.LOW
    suggested_cv: str = "swe"  # "swe" or "pm"


class Job(BaseModel):
    id: str  # sha256 hash of (normalized title + company + location)
    title: str
    company: str
    location: Optional[str] = None
    location_type: Optional[LocationType] = None
    source: str  # linkedin / jobstreet / glints / indeed / kalibrr
    url: str
    description: Optional[str] = None
    posted_at: Optional[datetime] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    easy_apply: bool = False

    # Ranking
    score: Optional[JobScore] = None

    # Tracking
    status: JobStatus = JobStatus.NEW
    notes: Optional[str] = None
    applied_at: Optional[datetime] = None


class CVProfile(BaseModel):
    id: str  # "swe" or "pm"
    skills: List[str] = []
    titles: List[str] = []
    years_experience: float = 0.0
    seniority: str = "entry"
    raw_text: str = ""


class ScrapeSummary(BaseModel):
    """Summary returned after each scrape run."""

    run_at: datetime = Field(default_factory=datetime.utcnow)
    total_scraped: int = 0
    new_jobs: int = 0
    duplicates_skipped: int = 0
    irrelevant_filtered: int = 0
    stale_purged: int = 0
    strong_matches: int = 0
    decent_matches: int = 0
    low_matches: int = 0
    errors: List[str] = []

    def add_error(self, source: str, msg: str) -> None:
        self.errors.append(f"[{source}] {msg}")
