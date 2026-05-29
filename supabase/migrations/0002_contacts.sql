-- ============================================================
-- Migration 0002 — Contact / People Outreach support
-- Run this in Supabase SQL Editor on databases created BEFORE
-- the contact-outreach feature was added. (Fresh installs already
-- get everything from supabase/schema.sql and do not need this file.)
--
-- Safe to run repeatedly: every statement is idempotent.
-- ============================================================

-- ── Enums ────────────────────────────────────────────────────
-- CREATE TYPE has no IF NOT EXISTS, so guard each with a DO block.

DO $$ BEGIN
  CREATE TYPE contact_role AS ENUM (
    'recruiter', 'talent_acquisition', 'hiring_manager', 'hr', 'unknown'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE contact_source AS ENUM ('company_site', 'inferred', 'linkedin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE email_status AS ENUM (
    'none', 'guessed', 'mx_valid', 'verified', 'invalid'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE contact_status AS ENUM (
    'new', 'drafted', 'contacted', 'replied', 'ignored'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── Table ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
  id              TEXT PRIMARY KEY,          -- sha256(linkedin_url | full_name|company|email)

  company         TEXT NOT NULL,
  company_domain  TEXT,

  full_name       TEXT NOT NULL,
  title           TEXT,                      -- the person's own job title
  role            contact_role NOT NULL DEFAULT 'unknown',

  email           TEXT,
  email_status    email_status NOT NULL DEFAULT 'none',
  linkedin_url    TEXT,

  source          contact_source NOT NULL,
  confidence      NUMERIC(4, 3) NOT NULL DEFAULT 0,  -- 0.000 – 1.000

  related_job_id  TEXT REFERENCES jobs(id) ON DELETE SET NULL,

  draft_message   TEXT,
  status          contact_status NOT NULL DEFAULT 'new',

  notes           TEXT,
  scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ──────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_contacts_company       ON contacts (company);
CREATE INDEX IF NOT EXISTS idx_contacts_related_job   ON contacts (related_job_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status        ON contacts (status);
CREATE INDEX IF NOT EXISTS idx_contacts_role          ON contacts (role);

-- ── Auto-update updated_at ───────────────────────────────────
-- Reuses set_updated_at() defined in schema.sql.

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
  BEFORE UPDATE ON contacts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Row-Level Security ───────────────────────────────────────
-- Personal tool: disabled so the service-role key can read/write freely.

ALTER TABLE contacts DISABLE ROW LEVEL SECURITY;
