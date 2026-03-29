-- ============================================================
-- Job Scraper — Supabase Schema
-- Run this in your Supabase SQL editor (Dashboard > SQL Editor)
-- ============================================================

-- ── Enums ────────────────────────────────────────────────────

CREATE TYPE location_type AS ENUM ('remote', 'hybrid', 'on-site');

CREATE TYPE job_status AS ENUM (
  'new',
  'saved',
  'applied',
  'interviewing',
  'offer',
  'rejected'
);

CREATE TYPE match_label AS ENUM ('Strong', 'Decent', 'Low');

CREATE TYPE cv_type AS ENUM ('swe', 'pm');

-- ── Tables ───────────────────────────────────────────────────

-- jobs: one row per unique job (deduped by id hash)
CREATE TABLE IF NOT EXISTS jobs (
  id              TEXT PRIMARY KEY,         -- sha256 hash of (title|company|location)

  -- Core info
  title           TEXT NOT NULL,
  company         TEXT NOT NULL,
  location        TEXT,
  location_type   location_type,
  source          TEXT NOT NULL,            -- linkedin / jobstreet / glints / indeed / kalibrr
  url             TEXT NOT NULL,
  description     TEXT,
  easy_apply      BOOLEAN NOT NULL DEFAULT FALSE,

  -- Dates
  posted_at       TIMESTAMPTZ,              -- when the employer posted it
  scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Match scoring
  match_score     NUMERIC(5, 2),            -- 0.00 – 100.00 overall weighted score
  skills_score    NUMERIC(5, 2),
  seniority_score NUMERIC(5, 2),
  recency_score   NUMERIC(5, 2),
  title_score     NUMERIC(5, 2),
  match_label     match_label,
  suggested_cv    cv_type,

  -- Application tracking
  status          job_status NOT NULL DEFAULT 'new',
  notes           TEXT,
  applied_at      TIMESTAMPTZ
);

-- cv_profiles: cached parsed data from the two CVs
CREATE TABLE IF NOT EXISTS cv_profiles (
  id               TEXT PRIMARY KEY,        -- 'swe' or 'pm'
  skills           TEXT[]   NOT NULL DEFAULT '{}',
  titles           TEXT[]   NOT NULL DEFAULT '{}',
  years_experience NUMERIC(4, 1) NOT NULL DEFAULT 0,
  seniority        TEXT     NOT NULL DEFAULT 'entry',
  raw_text         TEXT     NOT NULL DEFAULT '',
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- scrape_runs: audit log of every scraper execution
CREATE TABLE IF NOT EXISTS scrape_runs (
  id              BIGSERIAL PRIMARY KEY,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at     TIMESTAMPTZ,
  jobs_found      INT NOT NULL DEFAULT 0,
  jobs_new        INT NOT NULL DEFAULT 0,
  strong_matches  INT NOT NULL DEFAULT 0,
  email_sent      BOOLEAN NOT NULL DEFAULT FALSE,
  error_message   TEXT
);

-- ── Indexes ──────────────────────────────────────────────────

-- Dashboard default sort: highest score first
CREATE INDEX IF NOT EXISTS idx_jobs_match_score
  ON jobs (match_score DESC NULLS LAST);

-- Filter by label (Strong / Decent / Low)
CREATE INDEX IF NOT EXISTS idx_jobs_match_label
  ON jobs (match_label);

-- Filter by status (new / applied / etc.)
CREATE INDEX IF NOT EXISTS idx_jobs_status
  ON jobs (status);

-- Filter by source (linkedin / jobstreet / etc.)
CREATE INDEX IF NOT EXISTS idx_jobs_source
  ON jobs (source);

-- Filter by location type
CREATE INDEX IF NOT EXISTS idx_jobs_location_type
  ON jobs (location_type);

-- Sort / filter by post date (recency)
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at
  ON jobs (posted_at DESC NULLS LAST);

-- Sort by scrape time (for "new since last run" queries)
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at
  ON jobs (scraped_at DESC);

-- ── Auto-update updated_at ───────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_jobs_updated_at
  BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_cv_profiles_updated_at
  BEFORE UPDATE ON cv_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Row-Level Security ───────────────────────────────────────
-- This is a personal tool; we disable RLS so the service-role
-- key used by GitHub Actions can read/write freely.
-- If you ever expose the dashboard publicly, re-enable RLS
-- and add proper policies.

ALTER TABLE jobs          DISABLE ROW LEVEL SECURITY;
ALTER TABLE cv_profiles   DISABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs   DISABLE ROW LEVEL SECURITY;

-- ── Seed CV Profiles ─────────────────────────────────────────
-- Pre-load Dewangga's two CV profiles so the scorer works
-- even before the first PDF parse.

INSERT INTO cv_profiles (id, skills, titles, years_experience, seniority, raw_text)
VALUES
  (
    'swe',
    ARRAY[
      'React.js', 'Node.js', 'Express.js', '.NET Core', 'JavaScript', 'TypeScript',
      'PostgreSQL', 'SQL Server', 'Firebase', 'Firestore', 'Git', 'Jest',
      'OAuth 2.0', 'Tailwind CSS', 'REST APIs', 'CI/CD', 'HTML', 'CSS',
      'C', 'C++', 'Java', 'Postman', 'SendGrid', 'Google OAuth'
    ],
    ARRAY[
      'Software Engineer', 'Full-Stack Developer', 'Web Developer',
      'Frontend Developer', 'Backend Developer', 'IT Consultant',
      'Software Developer'
    ],
    1.5,
    'entry',
    'Full-Stack Software Engineer React Node.js .NET Computer Science Undergraduate DKSH Moflip COI Disclosure System Hackathon Portal GPA 3.91'
  ),
  (
    'pm',
    ARRAY[
      'Requirements Gathering', 'Stakeholder Management', 'Product Documentation',
      'Agile', 'Scrum', 'User Workflows', 'Acceptance Criteria', 'Google Analytics',
      'SQL', 'React.js', 'Node.js', '.NET Core', 'Firebase', 'Git',
      'REST API Design', 'CI/CD', 'Postman', 'Roadmap', 'UAT',
      'Cross-functional Collaboration', 'Product Delivery'
    ],
    ARRAY[
      'Product Manager', 'IT Consultant', 'Product Owner',
      'Business Analyst', 'Technical Product Manager'
    ],
    1.5,
    'entry',
    'Product Manager IT Applications Intern Product Engineering DKSH COI Disclosure System stakeholder requirements compliance roadmap UAT delivery GPA 3.91'
  )
ON CONFLICT (id) DO UPDATE
  SET skills           = EXCLUDED.skills,
      titles           = EXCLUDED.titles,
      years_experience = EXCLUDED.years_experience,
      seniority        = EXCLUDED.seniority,
      raw_text         = EXCLUDED.raw_text,
      updated_at       = NOW();
