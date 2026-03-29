from __future__ import annotations

import os
from typing import Optional

import yaml

try:
    import pdfplumber  # pip install pdfplumber

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from core.models import CVProfile

# ─── Public API ───────────────────────────────────────────────────────────────


def load_cv_profiles() -> tuple[CVProfile, CVProfile]:
    """
    Load both CV profiles (SWE and PM).

    Strategy:
    1. Always start from the structured data in config.yaml  — this guarantees
       the scorer has the right skills/titles even without PDF files present
       (e.g. first GitHub Actions run before PDFs are committed).
    2. If the PDF file exists on disk, extract its raw text and append any
       *additional* skills found there that are not already in the config list.
       This means updating the PDF later automatically enriches scoring without
       touching config.yaml.

    Returns:
        (swe_profile, pm_profile)
    """
    config = _load_config()
    swe_conf = config["cv_profiles"]["swe"]
    pm_conf = config["cv_profiles"]["pm"]

    swe_profile = _build_profile("swe", swe_conf)
    pm_profile = _build_profile("pm", pm_conf)

    return swe_profile, pm_profile


def load_single_profile(cv_id: str) -> CVProfile:
    """Load one CV profile by id ('swe' or 'pm')."""
    config = _load_config()
    conf = config["cv_profiles"][cv_id]
    return _build_profile(cv_id, conf)


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _build_profile(cv_id: str, conf: dict) -> CVProfile:
    """Build a CVProfile from the config dict, optionally enriched by PDF text."""
    skills: list[str] = list(conf.get("skills", []))
    titles: list[str] = list(conf.get("titles", []))
    keywords: list[str] = list(conf.get("keywords", []))
    years: float = float(conf.get("years_experience", 0.0))
    seniority: str = str(conf.get("seniority", "entry"))
    pdf_path: str = conf.get("path", "")

    raw_text = ""

    # ── Try to read the PDF ───────────────────────────────────────────────────
    abs_pdf_path = _resolve_path(pdf_path)
    if abs_pdf_path and os.path.exists(abs_pdf_path):
        raw_text = _extract_pdf_text(abs_pdf_path)
        if raw_text:
            # Augment skills with anything found in the PDF text
            extra_skills = _extract_extra_skills(raw_text, existing=skills)
            skills = skills + extra_skills
            print(
                f"  [{cv_id.upper()} CV] PDF parsed — "
                f"{len(raw_text)} chars, +{len(extra_skills)} extra skills"
            )
        else:
            print(
                f"  [{cv_id.upper()} CV] PDF found but no text extracted — using config only"
            )
    else:
        print(
            f"  [{cv_id.upper()} CV] No PDF at '{pdf_path}' — using config skills only"
        )

    return CVProfile(
        id=cv_id,
        skills=skills,
        titles=titles,
        years_experience=years,
        seniority=seniority,
        raw_text=raw_text or _build_fallback_text(skills, titles, keywords),
    )


def _extract_pdf_text(path: str) -> str:
    """Extract all text from a PDF using pdfplumber."""
    if not PDF_AVAILABLE:
        print("  ⚠️  pdfplumber not installed — cannot parse PDF")
        return ""
    try:
        pages: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
        return "\n\n".join(pages)
    except Exception as exc:
        print(f"  ⚠️  PDF parse error ({path}): {exc}")
        return ""


# ── Skills known to appear in job descriptions in the MY/ID market ────────────
# These are checked against the PDF text to auto-discover unlisted skills.
_KNOWN_SKILLS_VOCAB: list[str] = [
    # Languages
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "C#",
    "C++",
    "C",
    "Go",
    "Kotlin",
    "Swift",
    "PHP",
    "Ruby",
    "Rust",
    "Scala",
    # Frontend
    "React",
    "React.js",
    "Next.js",
    "Vue",
    "Vue.js",
    "Angular",
    "Tailwind",
    "Tailwind CSS",
    "Bootstrap",
    "HTML",
    "CSS",
    "SASS",
    "Redux",
    "Zustand",
    "Webpack",
    "Vite",
    # Backend
    "Node.js",
    "Express",
    "Express.js",
    "FastAPI",
    "Django",
    "Flask",
    ".NET",
    ".NET Core",
    "Spring",
    "Spring Boot",
    "Laravel",
    "REST API",
    "GraphQL",
    "gRPC",
    "Microservices",
    # Databases
    "PostgreSQL",
    "MySQL",
    "SQL Server",
    "SQLite",
    "MongoDB",
    "Redis",
    "Elasticsearch",
    "Firebase",
    "Firestore",
    "Supabase",
    "DynamoDB",
    "Cassandra",
    # Cloud & DevOps
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Terraform",
    "CI/CD",
    "GitHub Actions",
    "Jenkins",
    "Ansible",
    "Linux",
    "Nginx",
    "Vercel",
    "Netlify",
    # Tools
    "Git",
    "GitHub",
    "GitLab",
    "Postman",
    "JIRA",
    "Confluence",
    "Figma",
    "Notion",
    # Testing
    "Jest",
    "Pytest",
    "Cypress",
    "Playwright",
    "Unit Testing",
    # Auth & Security
    "OAuth",
    "OAuth 2.0",
    "JWT",
    "Firebase Auth",
    # Data / Analytics
    "Google Analytics",
    "Mixpanel",
    "Amplitude",
    "Tableau",
    "Pandas",
    "NumPy",
    "SQL",
    # PM / Soft
    "Agile",
    "Scrum",
    "Kanban",
    "JIRA",
    "Product Management",
    "Stakeholder Management",
    "Requirements Gathering",
    "Roadmap",
    "UAT",
    "User Stories",
    "Acceptance Criteria",
    "Google Analytics",
    "A/B Testing",
    "OKRs",
    "KPIs",
]


def _extract_extra_skills(raw_text: str, existing: list[str]) -> list[str]:
    """
    Scan raw PDF text for known skills not already in the profile's skill list.
    Case-insensitive comparison; returns new skills preserving canonical casing.
    """
    existing_lower = {s.lower() for s in existing}
    text_lower = raw_text.lower()
    extras: list[str] = []

    for skill in _KNOWN_SKILLS_VOCAB:
        if skill.lower() not in existing_lower and skill.lower() in text_lower:
            extras.append(skill)
            existing_lower.add(skill.lower())  # avoid adding duplicates

    return extras


def _build_fallback_text(
    skills: list[str], titles: list[str], keywords: list[str]
) -> str:
    """
    Build a synthetic 'raw_text' blob from structured config data.
    Used by the semantic embeddings model when no PDF text is available —
    it's better than an empty string and still captures key context.
    """
    parts = [
        "Skills: " + ", ".join(skills),
        "Job titles: " + ", ".join(titles),
    ]
    if keywords:
        parts.append("Keywords: " + ", ".join(keywords))
    return "\n".join(parts)


def _load_config() -> dict:
    """Load config.yaml relative to this file's location (scraper/)."""
    config_path = _resolve_path("config.yaml")
    if not config_path or not os.path.exists(config_path):
        raise FileNotFoundError(f"config.yaml not found. Expected at: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve_path(relative_path: str) -> Optional[str]:
    """
    Resolve a path relative to the scraper/ package root directory.
    Works regardless of the current working directory when the script runs.
    """
    if not relative_path:
        return None
    # __file__ is scraper/ranking/cv_parser.py → go up one level to scraper/
    scraper_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(scraper_root, relative_path)
