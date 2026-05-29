-- ============================================================
-- Migration 0002 — Work-authorization scoring + Apply Assistant
-- Run this in Supabase SQL Editor on databases created BEFORE
-- these features. Fresh installs get everything from schema.sql.
-- Safe to run repeatedly (idempotent).
-- ============================================================

-- Work-authorization flag set by the scorer.
--   TRUE  = candidate is authorised to work in the job's country
--   FALSE = role likely needs visa sponsorship / relocation
--   NULL  = country unknown (e.g. "Remote") — not penalised
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_authorized BOOLEAN;

-- Apply Assistant output: tailored cover letter + talking points (JSON).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS application_draft JSONB;
