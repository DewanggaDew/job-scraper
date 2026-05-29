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
    QUEUED_APPLY = "queued_apply"
    FAILED_APPLY = "failed_apply"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"


class MatchLabel(str, Enum):
    STRONG = "Strong"
    DECENT = "Decent"
    LOW = "Low"


class ContactRole(str, Enum):
    RECRUITER = "recruiter"
    TALENT_ACQUISITION = "talent_acquisition"
    HIRING_MANAGER = "hiring_manager"
    HR = "hr"
    UNKNOWN = "unknown"


class ContactSource(str, Enum):
    COMPANY_SITE = "company_site"
    INFERRED = "inferred"
    LINKEDIN = "linkedin"


class EmailStatus(str, Enum):
    NONE = "none"          # no email known
    GUESSED = "guessed"    # inferred from a name + domain pattern, unverified
    MX_VALID = "mx_valid"  # domain has MX records (mailbox not confirmed)
    VERIFIED = "verified"  # mailbox confirmed by an external provider
    INVALID = "invalid"    # known bad


class ContactStatus(str, Enum):
    NEW = "new"
    DRAFTED = "drafted"      # an outreach message has been drafted
    CONTACTED = "contacted"  # user has reached out
    REPLIED = "replied"
    IGNORED = "ignored"


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

    # Work authorization (None = unknown country, don't penalise)
    work_authorized: Optional[bool] = None

    # Tracking
    status: JobStatus = JobStatus.NEW
    notes: Optional[str] = None
    applied_at: Optional[datetime] = None
    auto_apply_error: Optional[str] = None
    auto_apply_attempted_at: Optional[datetime] = None


class Contact(BaseModel):
    """A person at a target company we may reach out to about a job."""

    id: str  # sha256 of linkedin_url if present else (full_name|company|email)
    company: str
    company_domain: Optional[str] = None

    full_name: str
    title: Optional[str] = None  # the person's own job title at the company
    role: ContactRole = ContactRole.UNKNOWN  # classified target-role bucket

    email: Optional[str] = None
    email_status: EmailStatus = EmailStatus.NONE
    linkedin_url: Optional[str] = None

    source: ContactSource
    confidence: float = 0.0  # 0–1, how sure we are this is a real, relevant contact

    related_job_id: Optional[str] = None  # the job that triggered this lookup

    # Outreach
    draft_message: Optional[str] = None
    status: ContactStatus = ContactStatus.NEW

    notes: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


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
    companies_processed: int = 0
    contacts_found: int = 0
    errors: List[str] = []

    def add_error(self, source: str, msg: str) -> None:
        self.errors.append(f"[{source}] {msg}")
