'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import {
  Job,
  JobStatus,
  MatchLabel,
  getMatchColor,
  getMatchDot,
  getSourceLabel,
  formatPostedDate,
  getStatusColor,
} from '@/types'

// ─── Pipeline column config ───────────────────────────────────────────────────

const PIPELINE_COLUMNS: {
  status: JobStatus
  label: string
  emoji: string
  headerColor: string
  dotColor: string
}[] = [
  { status: 'new',          label: 'New',          emoji: '🆕', headerColor: 'bg-blue-50   border-blue-200',   dotColor: 'bg-blue-400' },
  { status: 'saved',        label: 'Saved',        emoji: '🔖', headerColor: 'bg-indigo-50 border-indigo-200', dotColor: 'bg-indigo-400' },
  { status: 'applied',      label: 'Applied',      emoji: '📨', headerColor: 'bg-purple-50 border-purple-200', dotColor: 'bg-purple-400' },
  { status: 'interviewing', label: 'Interviewing', emoji: '💬', headerColor: 'bg-orange-50 border-orange-200', dotColor: 'bg-orange-400' },
  { status: 'offer',        label: 'Offer',        emoji: '🎉', headerColor: 'bg-green-50  border-green-200',  dotColor: 'bg-green-500' },
  { status: 'rejected',     label: 'Rejected',     emoji: '❌', headerColor: 'bg-red-50    border-red-200',    dotColor: 'bg-red-400' },
]

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TrackerPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [view, setView] = useState<'kanban' | 'list'>('kanban')
  const [selectedStatus, setSelectedStatus] = useState<JobStatus | 'all'>('all')

  // ── Fetch jobs ──────────────────────────────────────────────────────────────
  const fetchJobs = async () => {
    setLoading(true)
    const { data, error } = await supabase
      .from('jobs')
      .select('*')
      .neq('status', 'new')          // tracker focuses on jobs you've engaged with
      .order('updated_at', { ascending: false })
      .limit(300)

    if (!error && data) {
      setJobs(data as Job[])
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchJobs()
  }, [])

  // ── Status update ───────────────────────────────────────────────────────────
  const updateStatus = async (jobId: string, newStatus: JobStatus) => {
    setUpdatingId(jobId)
    const patch: Record<string, unknown> = { status: newStatus }
    if (newStatus === 'applied') {
      patch.applied_at = new Date().toISOString()
    }
    const { error } = await supabase.from('jobs').update(patch).eq('id', jobId)
    if (!error) {
      setJobs((prev) =>
        prev.map((j) =>
          j.id === jobId
            ? { ...j, status: newStatus, applied_at: newStatus === 'applied' ? new Date().toISOString() : j.applied_at }
            : j
        )
      )
    }
    setUpdatingId(null)
  }

  // ── Stats ───────────────────────────────────────────────────────────────────
  const stats = {
    saved:        jobs.filter((j) => j.status === 'saved').length,
    applied:      jobs.filter((j) => j.status === 'applied').length,
    interviewing: jobs.filter((j) => j.status === 'interviewing').length,
    offer:        jobs.filter((j) => j.status === 'offer').length,
    rejected:     jobs.filter((j) => j.status === 'rejected').length,
  }

  // ── Job groups ──────────────────────────────────────────────────────────────
  const jobsByStatus = (status: JobStatus) => jobs.filter((j) => j.status === status)

  const filteredJobs =
    selectedStatus === 'all' ? jobs : jobs.filter((j) => j.status === selectedStatus)

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Application Tracker</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Track your job applications through the hiring pipeline.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="px-3 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
          >
            + Add from Feed
          </Link>
          <button
            onClick={() => setView(view === 'kanban' ? 'list' : 'kanban')}
            className="px-3 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-300 hover:bg-gray-50 rounded-lg transition-colors"
          >
            {view === 'kanban' ? '📋 List View' : '🗂 Kanban View'}
          </button>
        </div>
      </div>

      {/* ── Pipeline stats ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <PipelineStat emoji="🔖" label="Saved"        value={stats.saved}        color="text-indigo-700" bg="bg-indigo-50" />
        <PipelineStat emoji="📨" label="Applied"      value={stats.applied}      color="text-purple-700" bg="bg-purple-50" />
        <PipelineStat emoji="💬" label="Interviewing" value={stats.interviewing} color="text-orange-700" bg="bg-orange-50" />
        <PipelineStat emoji="🎉" label="Offers"       value={stats.offer}        color="text-green-700"  bg="bg-green-50" />
        <PipelineStat emoji="❌" label="Rejected"     value={stats.rejected}     color="text-red-700"    bg="bg-red-50" />
      </div>

      {/* ── Conversion funnel ── */}
      {stats.applied > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">📈 Funnel</h2>
          <div className="flex items-center gap-2 flex-wrap text-sm">
            <FunnelStep label="Applied" value={stats.applied} total={stats.applied} color="bg-purple-500" />
            <FunnelArrow />
            <FunnelStep label="Interviewing" value={stats.interviewing} total={stats.applied} color="bg-orange-500" />
            <FunnelArrow />
            <FunnelStep label="Offers" value={stats.offer} total={stats.applied} color="bg-green-500" />
          </div>
          {stats.applied > 0 && (
            <p className="text-xs text-gray-400 mt-3">
              Interview rate:{' '}
              <span className="font-semibold text-gray-600">
                {stats.applied > 0 ? Math.round((stats.interviewing / stats.applied) * 100) : 0}%
              </span>
              {stats.interviewing > 0 && (
                <>
                  {' · '}Offer rate:{' '}
                  <span className="font-semibold text-gray-600">
                    {Math.round((stats.offer / stats.interviewing) * 100)}%
                  </span>
                </>
              )}
            </p>
          )}
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
              <div className="h-4 bg-gray-200 rounded animate-pulse w-20" />
              {[...Array(2)].map((_, j) => (
                <div key={j} className="h-16 bg-gray-100 rounded-lg animate-pulse" />
              ))}
            </div>
          ))}
        </div>
      )}

      {/* ── Empty state (not loading, no tracked jobs) ── */}
      {!loading && jobs.length === 0 && (
        <div className="text-center py-20 bg-white rounded-xl border border-dashed border-gray-300">
          <p className="text-5xl mb-4">📋</p>
          <p className="text-lg font-semibold text-gray-700">No tracked applications yet</p>
          <p className="text-sm text-gray-500 mt-1 max-w-sm mx-auto">
            Open a job from the feed and change its status to "Saved" or "Applied" to start tracking it here.
          </p>
          <Link
            href="/"
            className="inline-block mt-4 px-4 py-2 text-sm font-semibold text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
          >
            Browse Job Feed →
          </Link>
        </div>
      )}

      {/* ── Kanban board ── */}
      {!loading && jobs.length > 0 && view === 'kanban' && (
        <div className="overflow-x-auto no-scrollbar pb-4">
          <div className="flex gap-4 min-w-max">
            {PIPELINE_COLUMNS.filter((col) => col.status !== 'new').map((col) => {
              const colJobs = jobsByStatus(col.status)
              return (
                <div
                  key={col.status}
                  className="w-64 flex-shrink-0"
                >
                  {/* Column header */}
                  <div className={`flex items-center justify-between px-3 py-2 rounded-t-xl border-t border-x ${col.headerColor}`}>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${col.dotColor}`} />
                      <span className="text-sm font-semibold text-gray-700">{col.emoji} {col.label}</span>
                    </div>
                    <span className="text-xs font-bold text-gray-500 bg-white rounded-full px-2 py-0.5 border border-gray-200">
                      {colJobs.length}
                    </span>
                  </div>

                  {/* Job cards */}
                  <div className={`min-h-[120px] p-2 space-y-2 rounded-b-xl border ${col.headerColor}`}>
                    {colJobs.length === 0 ? (
                      <div className="flex items-center justify-center h-16 text-xs text-gray-400 italic">
                        No jobs here
                      </div>
                    ) : (
                      colJobs.map((job) => (
                        <KanbanCard
                          key={job.id}
                          job={job}
                          onStatusChange={updateStatus}
                          isUpdating={updatingId === job.id}
                        />
                      ))
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── List view ── */}
      {!loading && jobs.length > 0 && view === 'list' && (
        <div className="space-y-4">
          {/* Status filter pills */}
          <div className="flex flex-wrap gap-2">
            {([['all', 'All'] as const, ...PIPELINE_COLUMNS.filter(c => c.status !== 'new').map(c => [c.status, `${c.emoji} ${c.label}`] as const)]).map(([val, label]) => (
              <button
                key={val}
                onClick={() => setSelectedStatus(val as JobStatus | 'all')}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  selectedStatus === val
                    ? 'bg-green-600 text-white border border-green-600'
                    : 'bg-white text-gray-600 border border-gray-300 hover:border-gray-400'
                }`}
              >
                {label}
                {val !== 'all' && (
                  <span className={`ml-1.5 text-xs ${selectedStatus === val ? 'text-green-200' : 'text-gray-400'}`}>
                    {jobsByStatus(val as JobStatus).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* List table */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Job</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">Source</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Posted</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">Score</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredJobs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-gray-400 text-sm italic">
                      No jobs in this status
                    </td>
                  </tr>
                ) : (
                  filteredJobs.map((job) => (
                    <ListRow
                      key={job.id}
                      job={job}
                      onStatusChange={updateStatus}
                      isUpdating={updatingId === job.id}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Kanban card ──────────────────────────────────────────────────────────────

function KanbanCard({
  job,
  onStatusChange,
  isUpdating,
}: {
  job: Job
  onStatusChange: (id: string, status: JobStatus) => void
  isUpdating: boolean
}) {
  const matchDot = getMatchDot(job.match_label)
  const score = job.match_score

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow">
      {/* Score + source row */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${matchDot}`} />
          {score !== null && (
            <span className="text-xs font-bold text-gray-700">{score.toFixed(0)}</span>
          )}
          <span className="text-xs text-gray-400">{getSourceLabel(job.source)}</span>
        </div>
        {job.easy_apply && (
          <span className="text-[10px] bg-blue-100 text-blue-700 px-1 py-0.5 rounded-full font-medium">⚡</span>
        )}
      </div>

      {/* Title */}
      <Link
        href={`/jobs/${job.id}`}
        className="block text-sm font-semibold text-gray-900 hover:text-green-700 line-clamp-2 leading-snug transition-colors"
      >
        {job.title}
      </Link>
      <p className="text-xs text-gray-500 mt-0.5">{job.company}</p>

      {/* Location */}
      {job.location && (
        <p className="text-xs text-gray-400 mt-1 truncate">📍 {job.location}</p>
      )}

      {/* Posted date */}
      <p className="text-xs text-gray-400 mt-1">{formatPostedDate(job.posted_at)}</p>

      {/* CV suggestion */}
      {job.suggested_cv && (
        <span className={`inline-block mt-2 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
          job.suggested_cv === 'swe' ? 'bg-indigo-100 text-indigo-700' : 'bg-pink-100 text-pink-700'
        }`}>
          {job.suggested_cv === 'swe' ? 'SWE CV' : 'PM CV'}
        </span>
      )}

      {/* Quick status change */}
      <div className="mt-3 pt-2 border-t border-gray-100">
        <select
          disabled={isUpdating}
          value={job.status}
          onChange={(e) => onStatusChange(job.id, e.target.value as JobStatus)}
          className="w-full text-xs border border-gray-200 rounded-md px-2 py-1 bg-gray-50 focus:outline-none focus:ring-1 focus:ring-green-500 cursor-pointer disabled:opacity-50"
        >
          {PIPELINE_COLUMNS.filter(c => c.status !== 'new').map((col) => (
            <option key={col.status} value={col.status}>
              {col.emoji} {col.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

// ─── List row ─────────────────────────────────────────────────────────────────

function ListRow({
  job,
  onStatusChange,
  isUpdating,
}: {
  job: Job
  onStatusChange: (id: string, status: JobStatus) => void
  isUpdating: boolean
}) {
  const matchColorClass = getMatchColor(job.match_label)
  const dotClass = getMatchDot(job.match_label)

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      {/* Job title + company */}
      <td className="px-4 py-3">
        <Link href={`/jobs/${job.id}`} className="group">
          <p className="font-semibold text-gray-900 group-hover:text-green-700 transition-colors text-sm line-clamp-1">
            {job.title}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">{job.company}</p>
          {job.location && (
            <p className="text-xs text-gray-400 mt-0.5 hidden lg:block">
              📍 {job.location}
            </p>
          )}
        </Link>
      </td>

      {/* Source */}
      <td className="px-4 py-3 hidden sm:table-cell">
        <span className="text-xs text-gray-500">{getSourceLabel(job.source)}</span>
      </td>

      {/* Posted */}
      <td className="px-4 py-3 hidden md:table-cell">
        <span className="text-xs text-gray-500">{formatPostedDate(job.posted_at)}</span>
      </td>

      {/* Score */}
      <td className="px-4 py-3 hidden lg:table-cell">
        {job.match_score !== null ? (
          <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border ${matchColorClass}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
            {job.match_score.toFixed(0)}
          </span>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
      </td>

      {/* Status dropdown */}
      <td className="px-4 py-3">
        <select
          disabled={isUpdating}
          value={job.status}
          onChange={(e) => onStatusChange(job.id, e.target.value as JobStatus)}
          className="text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-green-500 cursor-pointer disabled:opacity-50"
        >
          {PIPELINE_COLUMNS.filter(c => c.status !== 'new').map((col) => (
            <option key={col.status} value={col.status}>
              {col.emoji} {col.label}
            </option>
          ))}
        </select>
      </td>

      {/* Action */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-green-700 hover:text-green-900 font-medium whitespace-nowrap"
            title="Open job posting"
          >
            Apply ↗
          </a>
          <Link
            href={`/jobs/${job.id}`}
            className="text-xs text-gray-500 hover:text-gray-700 font-medium whitespace-nowrap"
          >
            Details
          </Link>
        </div>
      </td>
    </tr>
  )
}

// ─── Supporting components ────────────────────────────────────────────────────

function PipelineStat({
  emoji,
  label,
  value,
  color,
  bg,
}: {
  emoji: string
  label: string
  value: number
  color: string
  bg: string
}) {
  return (
    <div className={`${bg} rounded-xl border border-gray-200 p-3 text-center`}>
      <p className="text-lg">{emoji}</p>
      <p className={`text-2xl font-bold ${color} mt-0.5`}>{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

function FunnelStep({
  label,
  value,
  total,
  color,
}: {
  label: string
  value: number
  total: number
  color: string
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 rounded-full w-24 bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-700">
        {value} <span className="text-gray-400 font-normal">{label}</span>
        {total > 0 && value > 0 && (
          <span className="text-gray-400 font-normal"> ({pct}%)</span>
        )}
      </span>
    </div>
  )
}

function FunnelArrow() {
  return <span className="text-gray-300 font-bold text-lg">›</span>
}
