'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
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
import { ExternalLink } from 'lucide-react'

const STATUS_OPTIONS: { value: JobStatus; label: string }[] = [
  { value: 'new', label: 'New' },
  { value: 'saved', label: 'Saved' },
  { value: 'applied', label: 'Applied' },
  { value: 'interviewing', label: 'Interviewing' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
]

const SCORE_DIMENSIONS = [
  {
    key: 'skills_score' as keyof Job,
    label: 'Skills match',
    description: 'Semantic overlap between your CV skills and the posting.',
    weight: '40%',
  },
  {
    key: 'seniority_score' as keyof Job,
    label: 'Seniority fit',
    description: 'How your level lines up with the role.',
    weight: '25%',
  },
  {
    key: 'recency_score' as keyof Job,
    label: 'Recency',
    description: 'Newer listings score higher.',
    weight: '20%',
  },
  {
    key: 'title_score' as keyof Job,
    label: 'Title match',
    description: 'Alignment with your target titles.',
    weight: '15%',
  },
]

function scoreTone(pct: number) {
  if (pct >= 75) return { bar: 'bg-emerald-500', text: 'text-emerald-400' }
  if (pct >= 50) return { bar: 'bg-amber-400', text: 'text-amber-400' }
  return { bar: 'bg-rose-500', text: 'text-rose-400' }
}

function matchScoreTextClass(label: MatchLabel | null) {
  switch (label) {
    case 'Strong':
      return 'text-emerald-400'
    case 'Decent':
      return 'text-amber-400'
    case 'Low':
      return 'text-rose-400'
    default:
      return 'text-muted-foreground'
  }
}

export default function JobDetailPage() {
  const params = useParams()
  const router = useRouter()
  const jobId = params?.id as string

  const [job, setJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  const [selectedStatus, setSelectedStatus] = useState<JobStatus>('new')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [descExpanded, setDescExpanded] = useState(false)

  useEffect(() => {
    if (!jobId) return

    async function fetchJob() {
      const { data, error } = await supabase.from('jobs').select('*').eq('id', jobId).single()

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

  async function handleSave() {
    if (!job) return
    setSaving(true)
    setSaveSuccess(false)

    const payload: Record<string, unknown> = {
      status: selectedStatus,
      notes: notes || null,
    }

    if (selectedStatus === 'applied' && job.status !== 'applied') {
      payload.applied_at = new Date().toISOString()
    }

    const { error } = await supabase.from('jobs').update(payload).eq('id', job.id)

    setSaving(false)
    if (!error) {
      setJob((prev) => (prev ? { ...prev, status: selectedStatus, notes: notes || null } : null))
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2500)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        <Skeleton className="h-4 w-24 bg-muted" />
        <Card className="border-border/80 py-6 shadow-none">
          <CardContent className="space-y-4">
            <Skeleton className="h-8 w-3/4 max-w-md bg-muted" />
            <Skeleton className="h-5 w-1/2 max-w-xs bg-muted" />
            <Skeleton className="h-10 w-40 bg-muted" />
          </CardContent>
        </Card>
        <Card className="border-border/80 py-6 shadow-none">
          <CardContent className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 w-full bg-muted" />
            ))}
          </CardContent>
        </Card>
      </div>
    )
  }

  if (notFound || !job) {
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <p className="text-sm font-medium text-foreground">Job not found</p>
        <p className="mt-1 text-sm text-muted-foreground">It may have been removed from the database.</p>
        <Link href="/" className={cn(buttonVariants({ variant: 'link' }), 'mt-6')}>
          Back to job feed
        </Link>
      </div>
    )
  }

  const score = job.match_score ?? 0
  const label = job.match_label
  const matchColorClass = getMatchColor(label)
  const dotClass = getMatchDot(label)
  const locTypeLabel = job.location_type
    ? { remote: 'Remote', hybrid: 'Hybrid', 'on-site': 'On-site' }[job.location_type] ?? job.location_type
    : null

  const descText = job.description ?? ''
  const descTrimmed = descText.length > 800 ? descText.slice(0, 800) + '…' : descText
  const showExpandBtn = descText.length > 800

  const borderAccent =
    label === 'Strong'
      ? 'ring-emerald-500/40'
      : label === 'Decent'
        ? 'ring-amber-500/40'
        : 'ring-border'

  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-16">
      <div>
        <button
          type="button"
          onClick={() => router.back()}
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          ← Back
        </button>
      </div>

      <Card className={cn('gap-0 border-border/80 py-0 shadow-none ring-1', borderAccent)}>
        <div
          className={cn(
            'flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4',
            label === 'Strong' && 'bg-emerald-500/10',
            label === 'Decent' && 'bg-amber-500/10',
            (!label || label === 'Low') && 'bg-muted/30'
          )}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium',
                matchColorClass
              )}
            >
              <span className={cn('size-2 shrink-0 rounded-full', dotClass)} />
              {label ?? 'Unscored'} match
            </span>
            {label && (
              <span className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">
                {score.toFixed(0)}
                <span className="text-base font-normal text-muted-foreground">/100</span>
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {job.easy_apply && (
              <Badge variant="secondary" className="font-medium">
                Easy apply
              </Badge>
            )}
            {job.suggested_cv && (
              <Badge variant="outline" className="font-medium">
                {job.suggested_cv === 'swe' ? 'SWE CV' : 'PM CV'}
              </Badge>
            )}
          </div>
        </div>

        <CardContent className="space-y-4 px-6 py-6">
          <div>
            <h1 className="text-xl font-semibold leading-tight tracking-tight text-foreground">{job.title}</h1>
            <p className="mt-1 text-base text-muted-foreground">{job.company}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            {locTypeLabel && <MetaPill>{locTypeLabel}</MetaPill>}
            {job.location && <MetaPill>{job.location}</MetaPill>}
            <MetaPill>
              <SourceDot source={job.source} />
              {getSourceLabel(job.source)}
            </MetaPill>
            <MetaPill>{formatPostedDate(job.posted_at)}</MetaPill>
            {job.scraped_at && (
              <MetaPill title={`Scraped at ${new Date(job.scraped_at).toLocaleString()}`}>
                Scraped {formatPostedDate(job.scraped_at)}
              </MetaPill>
            )}
          </div>

          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonVariants(), 'inline-flex gap-2')}
          >
            {job.easy_apply ? 'Easy apply' : 'Apply now'}
            <ExternalLink className="size-3.5 opacity-70" />
          </a>
        </CardContent>
      </Card>

      {job.match_score !== null && (
        <Card className="border-border/80 shadow-none">
          <CardHeader className="pb-2">
            <p className="text-sm font-medium">Match breakdown</p>
          </CardHeader>
          <CardContent className="space-y-4">
            {SCORE_DIMENSIONS.map((dim) => {
              const raw = job[dim.key] as number | null
              const pct = Math.round(Math.min(Math.max(raw ?? 0, 0), 100))
              const tone = scoreTone(pct)
              return (
                <div key={dim.key} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-medium text-foreground">{dim.label}</span>
                      <span className="hidden text-xs text-muted-foreground sm:inline">({dim.weight})</span>
                    </div>
                    <span className={cn('text-sm font-semibold tabular-nums', tone.text)}>
                      {raw !== null ? pct : '—'}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn('h-full rounded-full transition-all duration-500', tone.bar)}
                      style={{ width: raw !== null ? `${pct}%` : '0%' }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">{dim.description}</p>
                </div>
              )
            })}
            <Separator />
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Overall</span>
              <span className={cn('text-lg font-semibold tabular-nums', matchScoreTextClass(label))}>
                {score.toFixed(1)} / 100
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-border/80 shadow-none">
        <CardHeader className="pb-2">
          <p className="text-sm font-medium">Application tracker</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Status</label>
            <div className="flex flex-wrap gap-2">
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSelectedStatus(opt.value)}
                  className={cn(
                    'rounded-full border px-3 py-1.5 text-sm font-medium transition-colors',
                    selectedStatus === opt.value
                      ? getStatusColor(opt.value)
                      : 'border-border bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Notes</label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Recruiter, feedback, salary, follow-up…"
              rows={4}
              className="min-h-[100px] resize-none"
            />
          </div>

          {job.applied_at && (
            <p className="text-xs text-muted-foreground">
              Applied{' '}
              {new Date(job.applied_at).toLocaleDateString('en-MY', {
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
            </p>
          )}

          <div className="flex items-center gap-3">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
            {saveSuccess && <span className="text-sm text-emerald-400 animate-fade-in">Saved</span>}
          </div>
        </CardContent>
      </Card>

      {descText && (
        <Card className="border-border/80 shadow-none">
          <CardHeader className="pb-2">
            <p className="text-sm font-medium">Description</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
              {descExpanded ? descText : descTrimmed}
            </div>
            {showExpandBtn && (
              <Button variant="link" className="h-auto p-0 text-primary" onClick={() => setDescExpanded((v) => !v)}>
                {descExpanded ? 'Show less' : 'Show full description'}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="border-border/80 shadow-none">
        <CardHeader className="pb-2">
          <p className="text-sm font-medium">Details</p>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
            <MetaField label="Source" value={getSourceLabel(job.source)} />
            <MetaField label="Location type" value={locTypeLabel ?? '—'} />
            <MetaField label="Easy apply" value={job.easy_apply ? 'Yes' : 'No'} />
            <MetaField
              label="Suggested CV"
              value={job.suggested_cv === 'swe' ? 'SWE' : job.suggested_cv === 'pm' ? 'PM' : '—'}
            />
            <MetaField
              label="Posted"
              value={
                job.posted_at
                  ? new Date(job.posted_at).toLocaleDateString('en-MY', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })
                  : 'Unknown'
              }
            />
            <MetaField
              label="Scraped"
              value={new Date(job.scraped_at).toLocaleDateString('en-MY', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
              })}
            />
            <div className="col-span-2 sm:col-span-3">
              <MetaField
                label="Job URL"
                value={
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-primary hover:underline"
                  >
                    {job.url}
                  </a>
                }
              />
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}

function MetaPill({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <Badge variant="outline" title={title} className="h-6 font-normal text-muted-foreground">
      {children}
    </Badge>
  )
}

function MetaField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium text-foreground">{value}</dd>
    </div>
  )
}

function SourceDot({ source }: { source: string }) {
  const colors: Record<string, string> = {
    linkedin: 'bg-sky-400',
    jobstreet: 'bg-orange-400',
    glints: 'bg-violet-400',
    indeed: 'bg-blue-400',
    kalibrr: 'bg-emerald-400',
  }
  return <span className={cn('mr-1 inline-block size-1.5 rounded-full', colors[source] ?? 'bg-muted-foreground')} />
}
