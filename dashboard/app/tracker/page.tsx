'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { supabase } from '@/lib/supabase'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  Job,
  JobStatus,
  getMatchColor,
  getMatchDot,
  getSourceLabel,
  formatPostedDate,
} from '@/types'
import { LayoutGrid, List } from 'lucide-react'

const PIPELINE_COLUMNS: {
  status: JobStatus
  label: string
}[] = [
  { status: 'new', label: 'New' },
  { status: 'saved', label: 'Saved' },
  { status: 'applied', label: 'Applied' },
  { status: 'interviewing', label: 'Interviewing' },
  { status: 'offer', label: 'Offer' },
  { status: 'rejected', label: 'Rejected' },
]

const TRACK_STATUSES = PIPELINE_COLUMNS.filter((c) => c.status !== 'new')

export default function TrackerPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [view, setView] = useState<'kanban' | 'list'>('kanban')
  const [selectedStatus, setSelectedStatus] = useState<JobStatus | 'all'>('all')

  const fetchJobs = async () => {
    setLoading(true)
    const { data, error } = await supabase
      .from('jobs')
      .select('*')
      .neq('status', 'new')
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
            ? {
                ...j,
                status: newStatus,
                applied_at: newStatus === 'applied' ? new Date().toISOString() : j.applied_at,
              }
            : j
        )
      )
    }
    setUpdatingId(null)
  }

  const stats = {
    saved: jobs.filter((j) => j.status === 'saved').length,
    applied: jobs.filter((j) => j.status === 'applied').length,
    interviewing: jobs.filter((j) => j.status === 'interviewing').length,
    offer: jobs.filter((j) => j.status === 'offer').length,
    rejected: jobs.filter((j) => j.status === 'rejected').length,
  }

  const jobsByStatus = (status: JobStatus) => jobs.filter((j) => j.status === status)

  const filteredJobs =
    selectedStatus === 'all' ? jobs : jobs.filter((j) => j.status === selectedStatus)

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Application tracker</h1>
          <p className="text-sm text-muted-foreground">Pipeline for roles you have moved past &ldquo;new&rdquo;.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/" className={buttonVariants({ size: 'sm' })}>
            Add from feed
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setView(view === 'kanban' ? 'list' : 'kanban')}
            className="gap-1.5"
          >
            {view === 'kanban' ? <List className="size-3.5" /> : <LayoutGrid className="size-3.5" />}
            {view === 'kanban' ? 'List view' : 'Board view'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <PipelineStat label="Saved" value={stats.saved} accent="text-violet-400" />
        <PipelineStat label="Applied" value={stats.applied} accent="text-purple-400" />
        <PipelineStat label="Interviewing" value={stats.interviewing} accent="text-orange-400" />
        <PipelineStat label="Offers" value={stats.offer} accent="text-emerald-400" />
        <PipelineStat label="Rejected" value={stats.rejected} accent="text-rose-400" />
      </div>

      {stats.applied > 0 && (
        <Card className="border-border/80 shadow-none">
          <CardHeader className="pb-2">
            <p className="text-sm font-medium">Funnel</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <FunnelStep label="Applied" value={stats.applied} total={stats.applied} tone="bg-purple-500" />
              <FunnelArrow />
              <FunnelStep label="Interviewing" value={stats.interviewing} total={stats.applied} tone="bg-orange-500" />
              <FunnelArrow />
              <FunnelStep label="Offers" value={stats.offer} total={stats.applied} tone="bg-emerald-500" />
            </div>
            <p className="text-xs text-muted-foreground">
              Interview rate:{' '}
              <span className="font-medium text-foreground">
                {stats.applied > 0 ? Math.round((stats.interviewing / stats.applied) * 100) : 0}%
              </span>
              {stats.interviewing > 0 && (
                <>
                  {' '}
                  · Offer rate:{' '}
                  <span className="font-medium text-foreground">
                    {Math.round((stats.offer / stats.interviewing) * 100)}%
                  </span>
                </>
              )}
            </p>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {[...Array(5)].map((_, i) => (
            <Card key={i} className="border-border/80 shadow-none">
              <CardContent className="space-y-3 px-4 py-4">
                <Skeleton className="h-4 w-20 bg-muted" />
                <Skeleton className="h-16 w-full bg-muted" />
                <Skeleton className="h-16 w-full bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!loading && jobs.length === 0 && (
        <Card className="border-dashed border-border/80 py-16 shadow-none">
          <CardContent className="px-6 text-center">
            <p className="text-sm font-medium text-foreground">No tracked applications yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Mark jobs as saved or applied from the feed to see them here.
            </p>
            <Link href="/" className={cn(buttonVariants(), 'mt-6')}>
              Browse job feed
            </Link>
          </CardContent>
        </Card>
      )}

      {!loading && jobs.length > 0 && view === 'kanban' && (
        <div className="no-scrollbar overflow-x-auto pb-2">
          <div className="flex min-w-max gap-4">
            {TRACK_STATUSES.map((col) => {
              const colJobs = jobsByStatus(col.status)
              return (
                <div key={col.status} className="w-64 shrink-0">
                  <div className="flex items-center justify-between rounded-t-xl border border-b-0 border-border bg-muted/30 px-3 py-2">
                    <span className="text-sm font-medium">{col.label}</span>
                    <Badge variant="secondary" className="h-5 min-w-5 justify-center px-1.5 font-mono text-[10px]">
                      {colJobs.length}
                    </Badge>
                  </div>
                  <div className="min-h-[120px] space-y-2 rounded-b-xl border border-border bg-card/30 p-2">
                    {colJobs.length === 0 ? (
                      <p className="py-6 text-center text-xs text-muted-foreground">Empty</p>
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

      {!loading && jobs.length > 0 && view === 'list' && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <FilterPill
              active={selectedStatus === 'all'}
              onClick={() => setSelectedStatus('all')}
              label="All"
            />
            {TRACK_STATUSES.map((col) => (
              <FilterPill
                key={col.status}
                active={selectedStatus === col.status}
                onClick={() => setSelectedStatus(col.status)}
                label={col.label}
                count={jobsByStatus(col.status).length}
              />
            ))}
          </div>

          <Card className="overflow-hidden border-border/80 py-0 shadow-none">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">Job</TableHead>
                  <TableHead className="hidden text-muted-foreground sm:table-cell">Source</TableHead>
                  <TableHead className="hidden text-muted-foreground md:table-cell">Posted</TableHead>
                  <TableHead className="hidden text-muted-foreground lg:table-cell">Score</TableHead>
                  <TableHead className="text-muted-foreground">Status</TableHead>
                  <TableHead className="w-[100px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredJobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-12 text-center text-sm text-muted-foreground">
                      No jobs in this status
                    </TableCell>
                  </TableRow>
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
              </TableBody>
            </Table>
          </Card>
        </div>
      )}
    </div>
  )
}

function FilterPill({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean
  onClick: () => void
  label: string
  count?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors',
        active
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground'
      )}
    >
      {label}
      {count !== undefined && (
        <span className={cn('text-xs tabular-nums', active ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
          {count}
        </span>
      )}
    </button>
  )
}

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
    <Card className="gap-0 border-border/80 py-0 shadow-none ring-0">
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className={cn('size-2 shrink-0 rounded-full', matchDot)} />
            {score !== null && (
              <span className="text-xs font-semibold tabular-nums text-foreground">{score.toFixed(0)}</span>
            )}
            <span className="truncate text-xs text-muted-foreground">{getSourceLabel(job.source)}</span>
          </div>
          {job.easy_apply && (
            <Badge variant="outline" className="h-4 shrink-0 px-1 text-[9px]">
              Easy
            </Badge>
          )}
        </div>

        <Link
          href={`/jobs/${job.id}`}
          className="line-clamp-2 text-sm font-medium leading-snug text-foreground hover:text-primary"
        >
          {job.title}
        </Link>
        <p className="text-xs text-muted-foreground">{job.company}</p>
        {job.location && <p className="truncate text-xs text-muted-foreground">{job.location}</p>}
        <p className="text-xs text-muted-foreground">{formatPostedDate(job.posted_at)}</p>

        {job.suggested_cv && (
          <Badge variant="secondary" className="h-5 text-[10px]">
            {job.suggested_cv === 'swe' ? 'SWE CV' : 'PM CV'}
          </Badge>
        )}

        <StatusSelect
          value={job.status}
          disabled={isUpdating}
          onChange={(v) => onStatusChange(job.id, v)}
        />
      </CardContent>
    </Card>
  )
}

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
    <TableRow className="border-border">
      <TableCell>
        <Link href={`/jobs/${job.id}`} className="group block space-y-0.5">
          <p className="line-clamp-1 text-sm font-medium group-hover:text-primary">{job.title}</p>
          <p className="text-xs text-muted-foreground">{job.company}</p>
          {job.location && <p className="hidden text-xs text-muted-foreground lg:block">{job.location}</p>}
        </Link>
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        <span className="text-xs text-muted-foreground">{getSourceLabel(job.source)}</span>
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <span className="text-xs text-muted-foreground">{formatPostedDate(job.posted_at)}</span>
      </TableCell>
      <TableCell className="hidden lg:table-cell">
        {job.match_score !== null ? (
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
              matchColorClass
            )}
          >
            <span className={cn('size-1.5 shrink-0 rounded-full', dotClass)} />
            {job.match_score.toFixed(0)}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        <StatusSelect
          value={job.status}
          disabled={isUpdating}
          onChange={(v) => onStatusChange(job.id, v)}
        />
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center">
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-primary hover:underline"
          >
            Apply
          </a>
          <Link href={`/jobs/${job.id}`} className="text-xs text-muted-foreground hover:text-foreground">
            Details
          </Link>
        </div>
      </TableCell>
    </TableRow>
  )
}

function StatusSelect({
  value,
  disabled,
  onChange,
}: {
  value: JobStatus
  disabled: boolean
  onChange: (v: JobStatus) => void
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange(v as JobStatus)}
      disabled={disabled}
    >
      <SelectTrigger className="h-8 w-full min-w-0 text-xs" size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {TRACK_STATUSES.map((col) => (
          <SelectItem key={col.status} value={col.status}>
            {col.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function PipelineStat({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <Card className="border-border/80 py-3 shadow-none ring-1 ring-border/60">
      <CardContent className="space-y-0.5 px-3 py-0">
        <p className={cn('text-2xl font-semibold tabular-nums tracking-tight', accent)}>{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  )
}

function FunnelStep({
  label,
  value,
  total,
  tone,
}: {
  label: string
  value: number
  total: number
  tone: string
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{value}</span> {label}
        {total > 0 && value > 0 && <span className="text-muted-foreground"> ({pct}%)</span>}
      </span>
    </div>
  )
}

function FunnelArrow() {
  return <span className="text-muted-foreground">›</span>
}
