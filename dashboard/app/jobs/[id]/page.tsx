'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import {
  Job,
  JobStatus,
  MatchLabel,
  getMatchColor,
  getMatchDot,
  getStatusColor,
  getSourceLabel,
  formatPostedDate,
} from '@/types'

// ─── Status options ───────────────────────────────────────────────────────────

const STATUS_OPTIONS: { value: JobStatus; label: string; emoji: string }[] = [
  { value: 'new', label: 'New', emoji: '🆕' },
  { value: 'saved', label: 'Saved', emoji: '🔖' },
  { value: 'applied', label: 'Applied', emoji: '📨' },
  { value: 'interviewing', label: 'Interviewing', emoji: '💬' },
  { value: 'offer', label: 'Offer Received', emoji: '🎉' },
  { value: 'rejected', label: 'Rejected', emoji: '❌' },
]

// ─── Score dimension config ───────────────────────────────────────────────────

const SCORE_DIMENSIONS = [
  {
    key: 'skills_score' as keyof Job,
    label: 'Skills Match',
    description: 'How well your CV skills match the job requirements (semantic similarity)',
    weight: '40%',
    icon: '🛠️',
  },
  {
    key: 'seniority_score' as keyof Job,
    label: 'Seniority Fit',
    description: 'Alignment between your experience level and what the role requires',
    weight: '25%',
    icon: '📈',
  },
  {
    key: 'recency_score' as keyof Job,
    label: 'Recency',
    description: 'How recently the job was posted (newer = higher chance it\'s still open)',
    weight: '20%',
    icon: '🕐',
  },
  {
    key: 'title_score' as keyof Job,
    label: 'Title Match',
    description: 'How closely the job title matches your preferred titles',
    weight: '15%',
    icon: '🏷️',
  },
]

// ─── Page component ───────────────────────────────────────────────────────────

export default function JobDetailPage() {
  const params = useParams()
  const router = useRouter()
  const jobId = params?.id as string

  const [job, setJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  // Edit state
  const [selectedStatus, setSelectedStatus] = useState<JobStatus>('new')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [descExpanded, setDescExpanded] = useState(false)

  // ── Fetch job ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!jobId) return

    async function fetchJob() {
      const { data, error } = await supabase
        .from('jobs')
        .select('*')
        .eq('id', jobId)
        .single()

      if (error || !data) {
        setNotFound(true)
      } else {
        setJob(data as Job)
        setSelectedStatus(data.status as JobStatus)
        setNotes(data.notes ?? '')
      }
      setLoading(false)
    }

    fetchJob()
  }, [jobId])

  // ── Save status/notes ──────────────────────────────────────────────────────
  async function handleSave() {
    if (!job) return
    setSaving(true)
    setSaveSuccess(false)

    const payload: Record<string, unknown> = {
      status: selectedStatus,
      notes: notes || null,
    }

    // Auto-set applied_at when status changes to applied
    if (selectedStatus === 'applied' && job.status !== 'applied') {
      payload.applied_at = new Date().toISOString()
    }

    const { error } = await supabase
      .from('jobs')
      .update(payload)
      .eq('id', job.id)

    setSaving(false)
    if (!error) {
      setJob((prev) => prev ? { ...prev, status: selectedStatus, notes: notes || null } : null)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2500)
    }
  }

  // ── Loading ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="max-w-3xl mx-auto space-y-5 animate-pulse">
        <div className="h-6 bg-gray-200 rounded w-32" />
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div className="h-7 bg-gray-200 rounded w-3/4" />
          <div className="h-5 bg-gray-200 rounded w-1/2" />
          <div className="h-4 bg-gray-200 rounded w-1/3" />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-3">
          <div className="h-5 bg-gray-200 rounded w-32" />
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 bg-gray-200 rounded w-24" />
              <div className="h-3 bg-gray-200 rounded flex-1" />
              <div className="h-4 bg-gray-200 rounded w-8" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (notFound || !job) {
    return (
      <div className="text-center py-20">
        <p className="text-5xl mb-4">🔍</p>
        <p className="text-lg font-semibold text-gray-700">Job not found</p>
        <p className="text-sm text-gray-500 mt-1">It may have been removed from the database.</p>
        <Link href="/" className="inline-block mt-5 text-sm text-green-700 font-medium hover:underline">
          ← Back to job feed
        </Link>
      </div>
    )
  }

  const score = job.match_score ?? 0
  const label = job.match_label
  const matchColorClass = getMatchColor(label)
  const dotClass = getMatchDot(label)
  const locTypeLabel = job.location_type
    ? { remote: '🌐 Remote', hybrid: '🏠 Hybrid', 'on-site': '🏢 On-site' }[job.location_type] ?? job.location_type
    : null

  const descText = job.description ?? ''
  const descTrimmed = descText.length > 800 ? descText.slice(0, 800) + '…' : descText
  const showExpandBtn = descText.length > 800

  return (
    <div className="max-w-3xl mx-auto space-y-5 pb-12">

      {/* ── Back link ── */}
      <div>
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          ← Back
        </button>
      </div>

      {/* ── Header card ── */}
      <div className={`bg-white rounded-xl border-2 overflow-hidden ${label === 'Strong' ? 'border-green-400' : label === 'Decent' ? 'border-yellow-400' : 'border-gray-200'}`}>

        {/* Match score banner */}
        <div className={`px-6 py-3 flex items-center justify-between ${label === 'Strong' ? 'bg-green-50' : label === 'Decent' ? 'bg-yellow-50' : 'bg-gray-50'}`}>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 text-sm font-bold px-3 py-1 rounded-full border ${matchColorClass}`}>
              <span className={`w-2 h-2 rounded-full ${dotClass}`} />
              {label ?? 'Unscored'} Match
            </span>
            {label && (
              <span className="text-2xl font-bold text-gray-800">
                {score.toFixed(0)}
                <span className="text-base font-normal text-gray-400">/100</span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {job.easy_apply && (
              <span className="text-xs bg-blue-100 text-blue-700 px-2.5 py-1 rounded-full font-semibold">
                ⚡ Easy Apply
              </span>
            )}
            {job.suggested_cv && (
              <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${job.suggested_cv === 'swe' ? 'bg-indigo-100 text-indigo-700' : 'bg-pink-100 text-pink-700'}`}>
                📄 Use {job.suggested_cv === 'swe' ? 'SWE / Dev CV' : 'PM CV'}
              </span>
            )}
          </div>
        </div>

        {/* Job details */}
        <div className="px-6 py-5 space-y-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900 leading-tight">{job.title}</h1>
            <p className="text-base text-gray-700 font-medium mt-1">{job.company}</p>
          </div>

          {/* Meta pills */}
          <div className="flex flex-wrap gap-2">
            {locTypeLabel && (
              <MetaPill>{locTypeLabel}</MetaPill>
            )}
            {job.location && (
              <MetaPill>📍 {job.location}</MetaPill>
            )}
            <MetaPill>
              <SourceDot source={job.source} />
              {getSourceLabel(job.source)}
            </MetaPill>
            <MetaPill>🕐 {formatPostedDate(job.posted_at)}</MetaPill>
            {job.scraped_at && (
              <MetaPill title={`Scraped at ${new Date(job.scraped_at).toLocaleString()}`}>
                🔄 Scraped {formatPostedDate(job.scraped_at)}
              </MetaPill>
            )}
          </div>

          {/* Apply button */}
          <div>
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-green-600 text-white text-sm font-semibold rounded-lg hover:bg-green-700 active:bg-green-800 transition-colors"
            >
              {job.easy_apply ? '⚡ Easy Apply' : '🔗 Apply Now'}
              <span className="text-green-200">↗</span>
            </a>
          </div>
        </div>
      </div>

      {/* ── Score breakdown card ── */}
      {job.match_score !== null && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="text-base font-bold text-gray-900">Match Score Breakdown</h2>

          <div className="space-y-3">
            {SCORE_DIMENSIONS.map((dim) => {
              const raw = job[dim.key] as number | null
              const pct = Math.round(Math.min(Math.max(raw ?? 0, 0), 100))
              const barColor =
                pct >= 75 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-400'
              const textColor =
                pct >= 75 ? 'text-green-700' : pct >= 50 ? 'text-yellow-700' : 'text-red-600'

              return (
                <div key={dim.key} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{dim.icon}</span>
                      <span className="text-sm font-medium text-gray-700">{dim.label}</span>
                      <span className="text-xs text-gray-400 hidden sm:inline">({dim.weight})</span>
                    </div>
                    <span className={`text-sm font-bold ${textColor}`}>
                      {raw !== null ? pct : '—'}
                    </span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                      style={{ width: raw !== null ? `${pct}%` : '0%' }}
                    />
                  </div>
                  <p className="text-xs text-gray-400">{dim.description}</p>
                </div>
              )
            })}
          </div>

          {/* Overall */}
          <div className="mt-2 pt-4 border-t border-gray-100 flex items-center justify-between">
            <span className="text-sm font-bold text-gray-700">Overall Score</span>
            <span className={`text-lg font-extrabold ${matchColorClass.split(' ')[0]}`}>
              {score.toFixed(1)} / 100
            </span>
          </div>
        </div>
      )}

      {/* ── Application tracker card ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-bold text-gray-900">Application Tracker</h2>

        {/* Status selector */}
        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Status
          </label>
          <div className="flex flex-wrap gap-2">
            {STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setSelectedStatus(opt.value)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                  selectedStatus === opt.value
                    ? getStatusColor(opt.value) + ' border-transparent'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
                }`}
              >
                {opt.emoji} {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Notes
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Add notes — recruiter name, interview feedback, salary range, follow-up date…"
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 placeholder-gray-400 resize-none"
          />
        </div>

        {/* Applied date display */}
        {job.applied_at && (
          <p className="text-xs text-gray-400">
            ✅ Applied on {new Date(job.applied_at).toLocaleDateString('en-MY', {
              day: 'numeric', month: 'long', year: 'numeric',
            })}
          </p>
        )}

        {/* Save button */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-green-600 text-white text-sm font-semibold rounded-lg hover:bg-green-700 active:bg-green-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
          {saveSuccess && (
            <span className="text-sm text-green-600 font-medium animate-fade-in">
              ✓ Saved!
            </span>
          )}
        </div>
      </div>

      {/* ── Job description card ── */}
      {descText && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-3">
          <h2 className="text-base font-bold text-gray-900">Job Description</h2>
          <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
            {descExpanded ? descText : descTrimmed}
          </div>
          {showExpandBtn && (
            <button
              onClick={() => setDescExpanded((v) => !v)}
              className="text-sm text-green-700 font-medium hover:underline"
            >
              {descExpanded ? 'Show less ↑' : 'Show full description ↓'}
            </button>
          )}
        </div>
      )}

      {/* ── Metadata card ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-bold text-gray-900 mb-4">Details</h2>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
          <MetaField label="Source" value={getSourceLabel(job.source)} />
          <MetaField label="Location Type" value={locTypeLabel ?? '—'} />
          <MetaField label="Easy Apply" value={job.easy_apply ? 'Yes ⚡' : 'No'} />
          <MetaField label="Suggested CV" value={job.suggested_cv === 'swe' ? 'SWE / Dev CV' : job.suggested_cv === 'pm' ? 'PM CV' : '—'} />
          <MetaField label="Posted" value={job.posted_at ? new Date(job.posted_at).toLocaleDateString('en-MY', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Unknown'} />
          <MetaField label="Scraped" value={new Date(job.scraped_at).toLocaleDateString('en-MY', { day: 'numeric', month: 'short', year: 'numeric' })} />
          <div className="col-span-2 sm:col-span-3">
            <MetaField
              label="Job URL"
              value={
                <a
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-green-700 hover:underline truncate block max-w-sm"
                >
                  {job.url}
                </a>
              }
            />
          </div>
        </dl>
      </div>

    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function MetaPill({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 px-2.5 py-1 bg-gray-100 text-gray-600 text-xs font-medium rounded-full"
    >
      {children}
    </span>
  )
}

function MetaField({
  label,
  value,
}: {
  label: string
  value: React.ReactNode
}) {
  return (
    <div>
      <dt className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-0.5">{label}</dt>
      <dd className="text-sm text-gray-800 font-medium">{value}</dd>
    </div>
  )
}

function SourceDot({ source }: { source: string }) {
  const colors: Record<string, string> = {
    linkedin: 'bg-blue-500',
    jobstreet: 'bg-orange-500',
    glints: 'bg-purple-500',
    indeed: 'bg-blue-400',
    kalibrr: 'bg-green-500',
  }
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full mr-0.5 ${colors[source] ?? 'bg-gray-400'}`}
    />
  )
}
