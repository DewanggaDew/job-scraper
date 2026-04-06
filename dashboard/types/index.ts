export type LocationType = 'remote' | 'hybrid' | 'on-site'

export type JobStatus =
  | 'new'
  | 'saved'
  | 'applied'
  | 'interviewing'
  | 'offer'
  | 'rejected'

export type MatchLabel = 'Strong' | 'Decent' | 'Low'

export type CVType = 'swe' | 'pm'

export type JobSource =
  | 'linkedin'
  | 'jobstreet'
  | 'glints'
  | 'indeed'
  | 'kalibrr'

export interface JobScore {
  match_score: number
  skills_score: number
  seniority_score: number
  recency_score: number
  title_score: number
  match_label: MatchLabel
  suggested_cv: CVType
}

export interface Job {
  id: string
  title: string
  company: string
  location: string | null
  location_type: LocationType | null
  source: JobSource
  url: string
  description: string | null
  posted_at: string | null
  scraped_at: string
  easy_apply: boolean

  // Scores (nullable — unscored jobs may exist briefly)
  match_score: number | null
  skills_score: number | null
  seniority_score: number | null
  recency_score: number | null
  title_score: number | null
  match_label: MatchLabel | null
  suggested_cv: CVType | null

  // Application tracking
  status: JobStatus
  notes: string | null
  applied_at: string | null

  created_at: string
  updated_at: string
}

// ─── Filter & Sort State ──────────────────────────────────────────────────────

export interface JobFilters {
  source: JobSource | 'all'
  location_type: LocationType | 'all'
  match_label: MatchLabel | 'all'
  status: JobStatus | 'all'
  search: string
}

export type SortKey = 'match_score' | 'posted_at' | 'scraped_at' | 'company'
export type SortDir = 'asc' | 'desc'

export interface SortState {
  key: SortKey
  dir: SortDir
}

// ─── Dashboard Stats ──────────────────────────────────────────────────────────

export interface DashboardStats {
  total: number
  strong: number
  decent: number
  low: number
  new_today: number
  applied: number
  interviewing: number
}

// ─── Tracker Pipeline Column ──────────────────────────────────────────────────

export interface PipelineColumn {
  status: JobStatus
  label: string
  color: string
  jobs: Job[]
}

// ─── Status update payload (for PATCH calls) ─────────────────────────────────

export interface StatusUpdatePayload {
  status: JobStatus
  notes?: string
  applied_at?: string | null
}

// ─── Score colour helpers (used in multiple components) ──────────────────────

export function getMatchColor(label: MatchLabel | null): string {
  switch (label) {
    case 'Strong':
      return 'text-emerald-300 bg-emerald-500/15 border-emerald-500/35'
    case 'Decent':
      return 'text-amber-300 bg-amber-500/15 border-amber-500/35'
    case 'Low':
      return 'text-rose-300 bg-rose-500/15 border-rose-500/35'
    default:
      return 'text-muted-foreground bg-muted border-border'
  }
}

export function getMatchDot(label: MatchLabel | null): string {
  switch (label) {
    case 'Strong':
      return 'bg-emerald-400'
    case 'Decent':
      return 'bg-amber-400'
    case 'Low':
      return 'bg-rose-400'
    default:
      return 'bg-muted-foreground/50'
  }
}

export function getStatusColor(status: JobStatus): string {
  switch (status) {
    case 'new':
      return 'text-sky-300 bg-sky-500/15 border border-sky-500/30'
    case 'saved':
      return 'text-violet-300 bg-violet-500/15 border border-violet-500/30'
    case 'applied':
      return 'text-purple-300 bg-purple-500/15 border border-purple-500/30'
    case 'interviewing':
      return 'text-orange-300 bg-orange-500/15 border border-orange-500/30'
    case 'offer':
      return 'text-emerald-300 bg-emerald-500/15 border border-emerald-500/30'
    case 'rejected':
      return 'text-rose-300 bg-rose-500/15 border border-rose-500/30'
    default:
      return 'text-muted-foreground bg-muted border border-border'
  }
}

export function getSourceLabel(source: JobSource | string): string {
  const labels: Record<string, string> = {
    linkedin: 'LinkedIn',
    jobstreet: 'JobStreet',
    glints: 'Glints',
    indeed: 'Indeed',
    kalibrr: 'Kalibrr',
  }
  return labels[source] ?? source
}

export function formatPostedDate(postedAt: string | null): string {
  if (!postedAt) return 'Unknown date'
  const posted = new Date(postedAt)
  const now = new Date()
  const diffMs = now.getTime() - posted.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return posted.toLocaleDateString('en-MY', { day: 'numeric', month: 'short', year: 'numeric' })
}
