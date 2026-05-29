-- ============================================================
-- Migration 0001 — Auto-Apply support
-- Run this in Supabase SQL Editor on databases created BEFORE
-- auto-apply was added. (Fresh installs already get everything
-- from supabase/schema.sql and do not need this file.)
--
-- Safe to run repeatedly: every statement is idempotent.
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction
-- block, so run this file as plain statements (the Supabase SQL
-- Editor does this by default).
-- ============================================================

-- New job_status enum values used by the auto-applier.
ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'queued_apply';
ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'failed_apply';

-- New tracking columns on the jobs table.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS auto_apply_error TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS auto_apply_attempted_at TIMESTAMPTZ;
