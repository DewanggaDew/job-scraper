from __future__ import annotations

import re
from typing import Optional

from core.models import LocationType

# ─── Skill Taxonomy ───────────────────────────────────────────────────────────
# Ordered from most specific to most generic so partial matches don't shadow
# full ones (e.g. ".NET Core" is listed before ".NET").

KNOWN_SKILLS: list[str] = [
    # ── JavaScript / TypeScript ecosystem ────────────────────────────────────
    "Next.js",
    "Nuxt.js",
    "Nuxt",
    "React.js",
    "React Native",
    "React",
    "Vue.js",
    "Vue",
    "Angular",
    "Svelte",
    "Remix",
    "Node.js",
    "Express.js",
    "Express",
    "Nest.js",
    "NestJS",
    "TypeScript",
    "JavaScript",
    # ── Python ───────────────────────────────────────────────────────────────
    "FastAPI",
    "Django REST Framework",
    "Django",
    "Flask",
    "Celery",
    "Python",
    # ── JVM ──────────────────────────────────────────────────────────────────
    "Spring Boot",
    "Spring",
    "Kotlin",
    "Java",
    # ── .NET ─────────────────────────────────────────────────────────────────
    ".NET Core",
    ".NET",
    "ASP.NET",
    "C#",
    # ── PHP ──────────────────────────────────────────────────────────────────
    "Laravel",
    "Symfony",
    "PHP",
    # ── Go / Rust / Other ────────────────────────────────────────────────────
    "Go",
    "Golang",
    "Rust",
    "Ruby on Rails",
    "Ruby",
    "Scala",
    "C++",
    "C",
    # ── Databases ────────────────────────────────────────────────────────────
    "PostgreSQL",
    "MySQL",
    "MariaDB",
    "SQL Server",
    "Oracle DB",
    "MongoDB",
    "DynamoDB",
    "Cassandra",
    "Redis",
    "Elasticsearch",
    "Firestore",
    "Firebase",
    "Supabase",
    "PlanetScale",
    "SQL",
    "NoSQL",
    # ── Cloud & DevOps ───────────────────────────────────────────────────────
    "AWS Lambda",
    "Amazon Web Services",
    "AWS",
    "Google Cloud Platform",
    "GCP",
    "Google Cloud",
    "Microsoft Azure",
    "Azure",
    "Kubernetes",
    "K8s",
    "Docker",
    "Terraform",
    "Ansible",
    "CI/CD",
    "GitHub Actions",
    "GitLab CI",
    "Jenkins",
    "CircleCI",
    "Git",
    "GitHub",
    "GitLab",
    "Bitbucket",
    # ── APIs & Architecture ───────────────────────────────────────────────────
    "GraphQL",
    "REST API",
    "RESTful",
    "gRPC",
    "WebSocket",
    "Microservices",
    "Serverless",
    "Event-Driven",
    # ── Frontend tooling ─────────────────────────────────────────────────────
    "Tailwind CSS",
    "Tailwind",
    "Bootstrap",
    "SASS",
    "SCSS",
    "Webpack",
    "Vite",
    "Babel",
    "HTML5",
    "HTML",
    "CSS3",
    "CSS",
    # ── Testing ──────────────────────────────────────────────────────────────
    "Jest",
    "Pytest",
    "Cypress",
    "Playwright",
    "Selenium",
    "Unit Testing",
    "Integration Testing",
    "TDD",
    "BDD",
    # ── Auth & Security ───────────────────────────────────────────────────────
    "OAuth 2.0",
    "OAuth",
    "JWT",
    "SSO",
    "SAML",
    "OpenID Connect",
    "Firebase Auth",
    # ── Data & AI ────────────────────────────────────────────────────────────
    "Machine Learning",
    "Deep Learning",
    "TensorFlow",
    "PyTorch",
    "Pandas",
    "NumPy",
    "Scikit-learn",
    "Power BI",
    "Tableau",
    "Looker",
    "Data Analysis",
    # ── Product / PM ─────────────────────────────────────────────────────────
    "Product Management",
    "Product Strategy",
    "Product Roadmap",
    "Roadmap",
    "Requirements Gathering",
    "Business Requirements",
    "Stakeholder Management",
    "Stakeholder",
    "User Stories",
    "User Research",
    "Usability Testing",
    "Acceptance Criteria",
    "UAT",
    "Agile",
    "Scrum",
    "Kanban",
    "SAFe",
    "JIRA",
    "Confluence",
    "Notion",
    "Linear",
    "Trello",
    "Figma",
    "Sketch",
    "Wireframing",
    "Prototyping",
    "Google Analytics",
    "Mixpanel",
    "Amplitude",
    "Hotjar",
    "A/B Testing",
    "Experimentation",
    "Go-to-Market",
    "Product Launch",
    "OKRs",
    "KPIs",
    "Metrics",
    "Cross-functional",
    "Sprint",
    "Backlog",
    "Retrospective",
    # ── Tools & Infra ────────────────────────────────────────────────────────
    "Postman",
    "Swagger",
    "OpenAPI",
    "Linux",
    "Bash",
    "Shell",
    "Nginx",
    "Apache",
    "SendGrid",
    "Twilio",
    "Stripe",
    "PayPal",
]

# ─── Seniority Signals ────────────────────────────────────────────────────────

_SENIORITY_SIGNALS: dict[str, list[str]] = {
    "senior": [
        "senior",
        "sr.",
        "sr ",
        "lead",
        "principal",
        "staff engineer",
        "tech lead",
        "engineering manager",
        "head of",
        "director",
        "architect",
        "vp of",
        "vice president",
    ],
    "mid": [
        "mid-level",
        "mid level",
        "intermediate",
        "associate",
        "mid ",
        "mid-",
        "3+ years",
        "4+ years",
        "5+ years",
        "3 years",
        "4 years",
        "5 years",
    ],
    "entry": [
        "junior",
        "jr.",
        "jr ",
        "entry level",
        "entry-level",
        "graduate",
        "fresh graduate",
        "fresh grad",
        "freshgrad",
        "intern",
        "internship",
        "trainee",
        "graduate programme",
        "0-2 years",
        "0 - 2 years",
        "1-2 years",
        "1 - 2 years",
        "new grad",
        "no experience required",
    ],
}

# ─── Location-type Signals ────────────────────────────────────────────────────

_LOCATION_SIGNALS: dict[LocationType, list[str]] = {
    LocationType.REMOTE: [
        "fully remote",
        "100% remote",
        "remote only",
        "remote-first",
        "remote",
        "work from home",
        "wfh",
        "work from anywhere",
    ],
    LocationType.HYBRID: [
        "hybrid",
        "flexible working",
        "flexible work arrangement",
        "partly remote",
        "partial remote",
    ],
    LocationType.ON_SITE: [
        "on-site",
        "onsite",
        "on site",
        "in-office",
        "in office",
        "office-based",
        "office based",
    ],
}

# ─── Public API ───────────────────────────────────────────────────────────────


def extract_job_skills(description: str) -> list[str]:
    """
    Return a deduplicated list of recognised skills found in *description*.
    Matching is case-insensitive. More-specific skills are matched first so
    "React.js" shadows bare "React" — both are kept because they are distinct
    entries in the taxonomy.
    """
    if not description:
        return []

    found: list[str] = []
    seen_lower: set[str] = set()
    desc_lower = description.lower()

    for skill in KNOWN_SKILLS:
        skill_lower = skill.lower()
        if skill_lower in seen_lower:
            continue
        # Word-boundary-aware search: wrap the skill in a pattern that prevents
        # matching mid-word (e.g. "Go" should not match inside "Django").
        pattern = r"(?<![a-z0-9._\-])" + re.escape(skill_lower) + r"(?![a-z0-9._\-])"
        if re.search(pattern, desc_lower):
            found.append(skill)
            seen_lower.add(skill_lower)

    return found


def extract_seniority(title: str, description: str) -> str:
    """
    Infer the required seniority level ('entry', 'mid', 'senior') from the
    job title and description.  Returns 'mid' when no clear signal is found.
    """
    combined = f"{title} {description}".lower()

    # Check in order: senior → entry → mid (entry keywords are common in titles,
    # so we check senior first to avoid misclassifying "Senior Graduate Hire").
    for level in ("senior", "entry", "mid"):
        signals = _SENIORITY_SIGNALS[level]
        if any(sig in combined for sig in signals):
            return level

    return "mid"


def extract_years_required(description: str) -> Optional[float]:
    """
    Extract the minimum years of experience required from *description*.

    Handles patterns like:
      • "3+ years of experience"
      • "minimum 2 years"
      • "at least 4 years"
      • "3-5 years experience"
      • "2 to 4 years"
      • "fresh graduate (0 years)"
    """
    if not description:
        return None

    text = description.lower()

    patterns = [
        # "minimum X years" / "at least X years"
        r"(?:minimum|at\s+least|min\.?)\s+(\d+(?:\.\d+)?)\s*\+?\s*years?",
        # "X+ years of …"
        r"(\d+(?:\.\d+)?)\s*\+\s*years?\s+(?:of\s+)?(?:experience|exp\b)",
        # "X–Y years" → take the lower bound
        r"(\d+(?:\.\d+)?)\s*(?:–|-|to)\s*\d+\s*years?",
        # Generic "X years"
        r"(\d+(?:\.\d+)?)\s*years?\s+(?:of\s+)?(?:experience|exp|relevant|working)?",
        # "experience of X years"
        r"experience\s+of\s+(\d+(?:\.\d+)?)\s*\+?\s*years?",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                continue

    # Special case: fresh graduate / no experience
    if re.search(r"fresh\s*grad|no\s+experience\s+required|0\s*years?", text):
        return 0.0

    return None


def detect_location_type(
    title: str,
    description: str,
    raw_location: str = "",
) -> Optional[LocationType]:
    """
    Detect the location type (remote / hybrid / on-site) from any of the
    available text fields.  More-specific signals (e.g. "fully remote") are
    checked before generic ones.
    """
    combined = f"{title} {description} {raw_location}".lower()

    # Iterate in priority order
    for loc_type in (LocationType.REMOTE, LocationType.HYBRID, LocationType.ON_SITE):
        signals = _LOCATION_SIGNALS[loc_type]
        if any(sig in combined for sig in signals):
            return loc_type

    return None


def extract_job_summary(description: str, max_chars: int = 300) -> str:
    """
    Return a short plain-text summary of the job description suitable for
    display in emails and job cards (no HTML, trimmed to *max_chars*).
    """
    if not description:
        return ""

    # Strip HTML tags if present
    text = re.sub(r"<[^>]+>", " ", description)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= max_chars:
        return text

    # Trim at the last space before the cutoff
    trimmed = text[:max_chars]
    last_space = trimmed.rfind(" ")
    if last_space > max_chars // 2:
        trimmed = trimmed[:last_space]

    return trimmed + "…"
