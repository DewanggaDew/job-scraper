import { supabase } from '@/lib/supabase'
import { FilterSelect, HiddenFilters } from '@/components/job-feed-filters'
import Link from 'next/link'
import {
  Job,
  MatchLabel,
  JobStatus,
  LocationType,
  JobSource,
  getMatchColor,
  getMatchDot,
  getStatusColor,
  getSourceLabel,
  formatPostedDate,
} from '@/types'

// ─── Search params interface ──────────────────────────────────────────────────

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

// ─── Data fetching ────────────────────────────────────────────────────────────

async function fetchJobs(searchParams: PageProps['searchParams']): Promise<Job[]> {
  let query = supabase
    .from('jobs')
    .select('*')
    .limit(200)

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

  // Client-side text search (simple, avoids a full-text index requirement)
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

// ─── Page ─────────────────────────────────────────────────────────────────────

export const revalidate = 300 // revalidate every 5 minutes

export default async function JobFeedPage({ searchParams }: PageProps) {
  const [jobs, stats] = await Promise.all([fetchJobs(searchParams), fetchStats()])

  const activeSource = searchParams.source || 'all'
  const activeLabel = searchParams.label || 'all'
  const activeStatus = searchParams.status || 'all'
  const activeLocType = searchParams.location_type || 'all'
  const activeSort = searchParams.sort || 'score'
  const activeQ = searchParams.q || ''

  return (
    <div className="space-y-6">

      {/* ── Page header ── */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Job Feed</h1>
        <p className="text-sm text-gray-500 mt-1">
          Jobs are scraped every 4 hours and ranked by match with your CVs.
        </p>
      </div>

      {/* ── Stats bar ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Total Jobs" value={stats.total} color="text-gray-700" bg="bg-white" />
        <StatCard label="🟢 Strong" value={stats.strong} color="text-green-700" bg="bg-green-50" />
        <StatCard label="🟡 Decent" value={stats.decent} color="text-yellow-700" bg="bg-yellow-50" />
        <StatCard label="New Today" value={stats.new_today} color="text-blue-700" bg="bg-blue-50" />
        <StatCard label="Applied" value={stats.applied} color="text-purple-700" bg="bg-purple-50" />
        <StatCard label="Interviewing" value={stats.interviewing} color="text-orange-700" bg="bg-orange-50" />
      </div>

      {/* ── Filters ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="flex flex-wrap gap-3">

          {/* Search */}
          <form method="GET" className="flex-1 min-w-[200px]">
            <HiddenFilters current={searchParams} skip="q" />
            <input
              name="q"
              defaultValue={activeQ}
              placeholder="Search title, company, location…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            />
          </form>

          {/* Sort */}
          <FilterSelect
            label="Sort"
            name="sort"
            value={activeSort}
            current={searchParams}
            options={[
              { value: 'score', label: '⭐ Best Match' },
              { value: 'date', label: '🕐 Newest Posted' },
              { value: 'scraped', label: '🔄 Recently Scraped' },
              { value: 'company', label: '🏢 Company A–Z' },
            ]}
          />
        </div>

        <div className="flex flex-wrap gap-3">
          {/* Match label */}
          <FilterSelect
            label="Match"
            name="label"
            value={activeLabel}
            current={searchParams}
            options={[
              { value: 'all', label: 'All Matches' },
              { value: 'Strong', label: '🟢 Strong (75+)' },
              { value: 'Decent', label: '🟡 Decent (50–74)' },
              { value: 'Low', label: '🔴 Low (<50)' },
            ]}
          />

          {/* Status */}
          <FilterSelect
            label="Status"
            name="status"
            value={activeStatus}
            current={searchParams}
            options={[
              { value: 'all', label: 'All Statuses' },
              { value: 'new', label: '🆕 New' },
              { value: 'saved', label: '🔖 Saved' },
              { value: 'applied', label: '📨 Applied' },
              { value: 'interviewing', label: '💬 Interviewing' },
              { value: 'offer', label: '🎉 Offer' },
              { value: 'rejected', label: '❌ Rejected' },
            ]}
          />

          {/* Location type */}
          <FilterSelect
            label="Work Type"
            name="location_type"
            value={activeLocType}
            current={searchParams}
            options={[
              { value: 'all', label: 'All Types' },
              { value: 'remote', label: '🌐 Remote' },
              { value: 'hybrid', label: '🏠 Hybrid' },
              { value: 'on-site', label: '🏢 On-site' },
            ]}
          />

          {/* Source */}
          <FilterSelect
            label="Source"
            name="source"
            value={activeSource}
            current={searchParams}
            options={[
              { value: 'all', label: 'All Sources' },
              { value: 'linkedin', label: 'LinkedIn' },
              { value: 'jobstreet', label: 'JobStreet' },
              { value: 'glints', label: 'Glints' },
              { value: 'indeed', label: 'Indeed' },
              { value: 'kalibrr', label: 'Kalibrr' },
            ]}
          />

          {/* Clear filters */}
          {(activeLabel !== 'all' || activeStatus !== 'all' || activeLocType !== 'all' || activeSource !== 'all' || activeQ) && (
            <Link
              href="/"
              className="self-end px-3 py-2 text-sm text-red-600 hover:text-red-800 hover:bg-red-50 rounded-lg transition-colors border border-red-200"
            >
              ✕ Clear filters
            </Link>
          )}
        </div>
      </div>

      {/* ── Result count ── */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          Showing <span className="font-semibold text-gray-800">{jobs.length}</span> job{jobs.length !== 1 ? 's' : ''}
          {activeQ && <span> matching "<span className="font-medium">{activeQ}</span>"</span>}
        </p>
        {jobs.length > 0 && (
          <p className="text-xs text-gray-400">
            {jobs.filter(j => j.match_label === 'Strong').length} strong ·{' '}
            {jobs.filter(j => j.match_label === 'Decent').length} decent
          </p>
        )}
      </div>

      {/* ── Job cards ── */}
      {jobs.length === 0 ? (
        <EmptyState hasFilters={activeLabel !== 'all' || activeStatus !== 'all' || activeSource !== 'all' || !!activeQ} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Components ───────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  color,
  bg,
}: {
  label: string
  value: number
  color: string
  bg: string
}) {
  return (
    <div className={`${bg} rounded-xl border border-gray-200 p-3 text-center`}>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

function JobCard({ job }: { job: Job }) {
  const score = job.match_score ?? 0
  const label = job.match_label
  const matchColorClass = getMatchColor(label)
  const dotClass = getMatchDot(label)
  const statusColorClass = getStatusColor(job.status)
  const locTypeLabel = job.location_type
    ? { remote: '🌐 Remote', hybrid: '🏠 Hybrid', 'on-site': '🏢 On-site' }[job.location_type] ?? job.location_type
    : null

  return (
    <Link
      href={`/jobs/${job.id}`}
      className="group bg-white rounded-xl border border-gray-200 hover:border-green-400 hover:shadow-md transition-all duration-200 flex flex-col overflow-hidden"
    >
      {/* Score banner */}
      <div className={`px-4 py-2.5 flex items-center justify-between border-b ${label === 'Strong' ? 'bg-green-50 border-green-200' : label === 'Decent' ? 'bg-yellow-50 border-yellow-200' : 'bg-gray-50 border-gray-200'}`}>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full border ${matchColorClass}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
            {label ?? 'Unscored'}
          </span>
          {label && (
            <span className="text-sm font-bold text-gray-700">
              {score.toFixed(0)}<span className="text-xs font-normal text-gray-400">/100</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {job.easy_apply && (
            <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-medium">
              ⚡ Easy Apply
            </span>
          )}
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${statusColorClass}`}>
            {job.status}
          </span>
        </div>
      </div>

      {/* Main content */}
      <div className="px-4 py-3 flex-1 flex flex-col gap-1.5">
        <h3 className="font-semibold text-gray-900 text-sm leading-snug group-hover:text-green-700 transition-colors line-clamp-2">
          {job.title}
        </h3>
        <p className="text-sm text-gray-600 font-medium">{job.company}</p>

        <div className="flex flex-wrap gap-1.5 mt-1">
          {locTypeLabel && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
              {locTypeLabel}
            </span>
          )}
          {job.location && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full truncate max-w-[160px]">
              📍 {job.location}
            </span>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <SourceBadge source={job.source} />
          <span>·</span>
          <span>{formatPostedDate(job.posted_at)}</span>
        </div>
        {job.suggested_cv && (
          <span className={`text-xs font-medium px-1.5 py-0.5 rounded-full ${job.suggested_cv === 'swe' ? 'bg-indigo-100 text-indigo-700' : 'bg-pink-100 text-pink-700'}`}>
            {job.suggested_cv === 'swe' ? 'SWE CV' : 'PM CV'}
          </span>
        )}
      </div>

      {/* Score mini-bars */}
      {job.match_score !== null && (
        <div className="px-4 pb-3 grid grid-cols-4 gap-1">
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
    pct >= 75 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-400'

  return (
    <div className="flex flex-col gap-0.5">
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[9px] text-gray-400 text-center">{label}</span>
    </div>
  )
}

function SourceBadge({ source }: { source: string }) {
  const colors: Record<string, string> = {
    linkedin: 'text-blue-600',
    jobstreet: 'text-orange-600',
    glints: 'text-purple-600',
    indeed: 'text-blue-500',
    kalibrr: 'text-green-600',
  }
  return (
    <span className={`font-medium ${colors[source] ?? 'text-gray-500'}`}>
      {getSourceLabel(source)}
    </span>
  )
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="text-center py-20 bg-white rounded-xl border border-dashed border-gray-300">
      <p className="text-4xl mb-4">🔍</p>
      {hasFilters ? (
        <>
          <p className="text-lg font-semibold text-gray-700">No jobs match your filters</p>
          <p className="text-sm text-gray-500 mt-1">Try adjusting or clearing the filters above.</p>
          <Link href="/" className="inline-block mt-4 text-sm text-green-700 font-medium hover:underline">
            Clear all filters
          </Link>
        </>
      ) : (
        <>
          <p className="text-lg font-semibold text-gray-700">No jobs scraped yet</p>
          <p className="text-sm text-gray-500 mt-1 max-w-sm mx-auto">
            The scraper runs every 4 hours via GitHub Actions. You can also trigger a manual run from the Actions tab.
          </p>
        </>
      )}
    </div>
  )
}
