import { supabase } from '@/lib/supabase'
import { FilterSelect, HiddenFilters } from '@/components/job-feed-filters'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  Job,
  MatchLabel,
  JobStatus,
  getMatchColor,
  getMatchDot,
  getStatusColor,
  getSourceLabel,
  formatPostedDate,
} from '@/types'

interface PageProps {
  searchParams: {
    source?: string
    label?: string
    status?: string
    location_type?: string
    sort?: string
    q?: string
  }
}

async function fetchJobs(searchParams: PageProps['searchParams']): Promise<Job[]> {
  let query = supabase.from('jobs').select('*').limit(200)

  if (searchParams.source && searchParams.source !== 'all') {
    query = query.eq('source', searchParams.source)
  }
  if (searchParams.label && searchParams.label !== 'all') {
    query = query.eq('match_label', searchParams.label)
  }
  if (searchParams.status && searchParams.status !== 'all') {
    query = query.eq('status', searchParams.status)
  }
  if (searchParams.location_type && searchParams.location_type !== 'all') {
    query = query.eq('location_type', searchParams.location_type)
  }

  const sort = searchParams.sort || 'score'
  if (sort === 'date') {
    query = query.order('posted_at', { ascending: false, nullsFirst: false })
  } else if (sort === 'scraped') {
    query = query.order('scraped_at', { ascending: false })
  } else if (sort === 'company') {
    query = query.order('company', { ascending: true })
  } else {
    query = query.order('match_score', { ascending: false, nullsFirst: false })
  }

  const { data, error } = await query
  if (error) {
    console.error('Failed to fetch jobs:', error)
    return []
  }

  let jobs = (data as Job[]) ?? []

  if (searchParams.q) {
    const q = searchParams.q.toLowerCase()
    jobs = jobs.filter(
      (j) =>
        j.title.toLowerCase().includes(q) ||
        j.company.toLowerCase().includes(q) ||
        (j.location ?? '').toLowerCase().includes(q)
    )
  }

  return jobs
}

async function fetchStats() {
  const { data } = await supabase.from('jobs').select('match_label, status, scraped_at')
  const rows = data ?? []

  const todayStart = new Date()
  todayStart.setHours(0, 0, 0, 0)

  return {
    total: rows.length,
    strong: rows.filter((r) => r.match_label === 'Strong').length,
    decent: rows.filter((r) => r.match_label === 'Decent').length,
    applied: rows.filter((r) => r.status === 'applied').length,
    interviewing: rows.filter((r) => r.status === 'interviewing').length,
    new_today: rows.filter((r) => r.scraped_at && new Date(r.scraped_at) >= todayStart).length,
  }
}

export const revalidate = 300

export default async function JobFeedPage({ searchParams }: PageProps) {
  const [jobs, stats] = await Promise.all([fetchJobs(searchParams), fetchStats()])

  const activeSource = searchParams.source || 'all'
  const activeLabel = searchParams.label || 'all'
  const activeStatus = searchParams.status || 'all'
  const activeLocType = searchParams.location_type || 'all'
  const activeSort = searchParams.sort || 'score'
  const activeQ = searchParams.q || ''

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Job feed</h1>
        <p className="text-sm text-muted-foreground">
          Scraped every 4 hours and ranked against your CVs.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Total" value={stats.total} />
        <StatCard label="Strong" value={stats.strong} accent="text-emerald-400" />
        <StatCard label="Decent" value={stats.decent} accent="text-amber-400" />
        <StatCard label="New today" value={stats.new_today} accent="text-sky-400" />
        <StatCard label="Applied" value={stats.applied} accent="text-violet-400" />
        <StatCard label="Interviewing" value={stats.interviewing} accent="text-orange-400" />
      </div>

      <Card className="gap-0 border-border/80 py-4 shadow-none">
        <CardContent className="space-y-4 px-4">
          <div className="flex flex-wrap items-end gap-3">
            <form method="GET" className="min-w-[200px] flex-1 space-y-1.5">
              <HiddenFilters current={searchParams} skip="q" />
              <label className="text-xs font-medium text-muted-foreground">Search</label>
              <Input name="q" defaultValue={activeQ} placeholder="Title, company, location…" />
            </form>
            <FilterSelect
              label="Sort"
              name="sort"
              value={activeSort}
              current={searchParams}
              options={[
                { value: 'score', label: 'Best match' },
                { value: 'date', label: 'Newest posted' },
                { value: 'scraped', label: 'Recently scraped' },
                { value: 'company', label: 'Company A–Z' },
              ]}
            />
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <FilterSelect
              label="Match"
              name="label"
              value={activeLabel}
              current={searchParams}
              options={[
                { value: 'all', label: 'All matches' },
                { value: 'Strong', label: 'Strong (75+)' },
                { value: 'Decent', label: 'Decent (50–74)' },
                { value: 'Low', label: 'Low (<50)' },
              ]}
            />
            <FilterSelect
              label="Status"
              name="status"
              value={activeStatus}
              current={searchParams}
              options={[
                { value: 'all', label: 'All statuses' },
                { value: 'new', label: 'New' },
                { value: 'saved', label: 'Saved' },
                { value: 'applied', label: 'Applied' },
                { value: 'interviewing', label: 'Interviewing' },
                { value: 'offer', label: 'Offer' },
                { value: 'rejected', label: 'Rejected' },
              ]}
            />
            <FilterSelect
              label="Work type"
              name="location_type"
              value={activeLocType}
              current={searchParams}
              options={[
                { value: 'all', label: 'All types' },
                { value: 'remote', label: 'Remote' },
                { value: 'hybrid', label: 'Hybrid' },
                { value: 'on-site', label: 'On-site' },
              ]}
            />
            <FilterSelect
              label="Source"
              name="source"
              value={activeSource}
              current={searchParams}
              options={[
                { value: 'all', label: 'All sources' },
                { value: 'linkedin', label: 'LinkedIn' },
                { value: 'jobstreet', label: 'JobStreet' },
                { value: 'glints', label: 'Glints' },
                { value: 'indeed', label: 'Indeed' },
                { value: 'kalibrr', label: 'Kalibrr' },
              ]}
            />
            {(activeLabel !== 'all' ||
              activeStatus !== 'all' ||
              activeLocType !== 'all' ||
              activeSource !== 'all' ||
              activeQ) && (
              <Link
                href="/"
                className={cn(
                  buttonVariants({ variant: 'outline', size: 'sm' }),
                  'border-destructive/40 text-destructive hover:bg-destructive/10'
                )}
              >
                Clear filters
              </Link>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{jobs.length}</span> jobs
          {activeQ && (
            <>
              {' '}
              matching &ldquo;<span className="text-foreground">{activeQ}</span>&rdquo;
            </>
          )}
        </p>
        {jobs.length > 0 && (
          <p className="text-xs text-muted-foreground">
            {jobs.filter((j) => j.match_label === 'Strong').length} strong ·{' '}
            {jobs.filter((j) => j.match_label === 'Decent').length} decent
          </p>
        )}
      </div>

      {jobs.length === 0 ? (
        <EmptyState
          hasFilters={
            activeLabel !== 'all' || activeStatus !== 'all' || activeSource !== 'all' || !!activeQ
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent?: string
}) {
  return (
    <Card className="border-border/80 py-3 shadow-none ring-1 ring-border/60">
      <CardContent className="space-y-0.5 px-3 py-0">
        <p className={cn('text-2xl font-semibold tabular-nums tracking-tight', accent ?? 'text-foreground')}>
          {value}
        </p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  )
}

function JobCard({ job }: { job: Job }) {
  const score = job.match_score ?? 0
  const label = job.match_label
  const matchColorClass = getMatchColor(label)
  const dotClass = getMatchDot(label)
  const statusColorClass = getStatusColor(job.status)
  const locTypeLabel = job.location_type
    ? { remote: 'Remote', hybrid: 'Hybrid', 'on-site': 'On-site' }[job.location_type] ?? job.location_type
    : null

  const bannerTint =
    label === 'Strong'
      ? 'bg-emerald-500/10'
      : label === 'Decent'
        ? 'bg-amber-500/10'
        : 'bg-muted/40'

  return (
    <Link
      href={`/jobs/${job.id}`}
      className="group flex flex-col overflow-hidden rounded-xl bg-card text-card-foreground ring-1 ring-border transition-[box-shadow,ring-color] hover:ring-ring/50"
    >
      <div className={cn('flex items-center justify-between border-b border-border px-4 py-2.5', bannerTint)}>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium',
              matchColorClass
            )}
          >
            <span className={cn('size-1.5 shrink-0 rounded-full', dotClass)} />
            {label ?? 'Unscored'}
          </span>
          {label && (
            <span className="text-sm font-semibold tabular-nums text-foreground">
              {score.toFixed(0)}
              <span className="text-xs font-normal text-muted-foreground">/100</span>
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {job.easy_apply && (
            <Badge variant="secondary" className="h-5 text-[10px] font-medium">
              Easy apply
            </Badge>
          )}
          <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium capitalize', statusColorClass)}>
            {job.status}
          </span>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-1.5 px-4 py-3">
        <h3 className="line-clamp-2 text-sm font-medium leading-snug text-foreground group-hover:text-primary">
          {job.title}
        </h3>
        <p className="text-sm text-muted-foreground">{job.company}</p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {locTypeLabel && (
            <Badge variant="outline" className="h-5 font-normal text-muted-foreground">
              {locTypeLabel}
            </Badge>
          )}
          {job.location && (
            <Badge variant="outline" className="h-5 max-w-[11rem] truncate font-normal text-muted-foreground">
              {job.location}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border bg-muted/20 px-4 py-2">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <SourceBadge source={job.source} />
          <span className="text-border">·</span>
          <span>{formatPostedDate(job.posted_at)}</span>
        </div>
        {job.suggested_cv && (
          <Badge variant="secondary" className="h-5 text-[10px]">
            {job.suggested_cv === 'swe' ? 'SWE CV' : 'PM CV'}
          </Badge>
        )}
      </div>

      {job.match_score !== null && (
        <div className="grid grid-cols-4 gap-2 px-4 pb-3">
          <ScoreMiniBar label="Skills" value={job.skills_score} />
          <ScoreMiniBar label="Level" value={job.seniority_score} />
          <ScoreMiniBar label="Recent" value={job.recency_score} />
          <ScoreMiniBar label="Title" value={job.title_score} />
        </div>
      )}
    </Link>
  )
}

function ScoreMiniBar({ label, value }: { label: string; value: number | null }) {
  const pct = Math.round(Math.min(Math.max(value ?? 0, 0), 100))
  const barColor =
    pct >= 75 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-400' : 'bg-rose-500'

  return (
    <div className="flex flex-col gap-0.5">
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-center text-[9px] text-muted-foreground">{label}</span>
    </div>
  )
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    linkedin: 'text-sky-400',
    jobstreet: 'text-orange-400',
    glints: 'text-violet-400',
    indeed: 'text-blue-400',
    kalibrr: 'text-emerald-400',
  }
  return <span className={cn('font-medium', colors[source] ?? 'text-muted-foreground')}>{getSourceLabel(source)}</span>
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <Card className="border-dashed border-border/80 py-16 shadow-none">
      <CardContent className="px-6 text-center">
        <p className="text-sm font-medium text-foreground">
          {hasFilters ? 'No jobs match your filters' : 'No jobs scraped yet'}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {hasFilters
            ? 'Adjust or clear filters to see more results.'
            : 'The scraper runs on a schedule. You can trigger a manual run from GitHub Actions.'}
        </p>
        {hasFilters && (
          <Link
            href="/"
            className={cn(buttonVariants({ variant: 'link' }), 'mt-4 h-auto p-0')}
          >
            Clear all filters
          </Link>
        )}
      </CardContent>
    </Card>
  )
}
