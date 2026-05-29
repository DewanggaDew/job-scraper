'use client'

import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import {
  Contact,
  ContactStatus,
  getContactRoleLabel,
  getContactStatusColor,
  getEmailStatusColor,
  getEmailStatusLabel,
} from '@/types'
import { Copy, ExternalLink, Check } from 'lucide-react'

const STATUS_OPTIONS: { value: ContactStatus; label: string }[] = [
  { value: 'new', label: 'New' },
  { value: 'drafted', label: 'Drafted' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'replied', label: 'Replied' },
  { value: 'ignored', label: 'Ignored' },
]

export function ContactsPanel({ jobId }: { jobId: string }) {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!jobId) return
    let active = true
    async function fetchContacts() {
      const { data } = await supabase
        .from('contacts')
        .select('*')
        .eq('related_job_id', jobId)
        .order('confidence', { ascending: false })
      if (active) {
        setContacts((data as Contact[]) ?? [])
        setLoading(false)
      }
    }
    fetchContacts()
    return () => {
      active = false
    }
  }, [jobId])

  if (loading) {
    return (
      <Card className="border-border/80 shadow-none">
        <CardHeader className="pb-2">
          <p className="text-sm font-medium">People at this company</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {[1, 2].map((i) => (
            <Skeleton key={i} className="h-20 w-full bg-muted" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (contacts.length === 0) {
    return (
      <Card className="border-border/80 shadow-none">
        <CardHeader className="pb-2">
          <p className="text-sm font-medium">People at this company</p>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No contacts found yet. The contact-finder runs after each scrape for
            companies behind your strong/saved matches.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-border/80 shadow-none">
      <CardHeader className="pb-2">
        <p className="text-sm font-medium">People at this company</p>
        <p className="text-xs text-muted-foreground">
          Outreach is yours to send — review the draft before reaching out.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {contacts.map((c) => (
          <ContactCard key={c.id} contact={c} />
        ))}
      </CardContent>
    </Card>
  )
}

function ContactCard({ contact }: { contact: Contact }) {
  const [status, setStatus] = useState<ContactStatus>(contact.status)
  const [copied, setCopied] = useState<'email' | 'message' | null>(null)

  async function updateStatus(next: ContactStatus) {
    setStatus(next)
    await supabase.from('contacts').update({ status: next }).eq('id', contact.id)
  }

  async function copy(text: string, which: 'email' | 'message') {
    await navigator.clipboard.writeText(text)
    setCopied(which)
    setTimeout(() => setCopied(null), 1800)
  }

  return (
    <div className="rounded-lg border border-border/80 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-foreground">{contact.full_name}</p>
          <p className="text-sm text-muted-foreground">
            {contact.title || getContactRoleLabel(contact.role)}
          </p>
        </div>
        <Badge variant="outline" className="font-medium">
          {getContactRoleLabel(contact.role)}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {contact.email && (
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium',
              getEmailStatusColor(contact.email_status)
            )}
            title={getEmailStatusLabel(contact.email_status)}
          >
            {contact.email}
          </span>
        )}
        {contact.email && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 px-2 text-xs"
            onClick={() => copy(contact.email!, 'email')}
          >
            {copied === 'email' ? <Check className="size-3" /> : <Copy className="size-3" />}
            Copy
          </Button>
        )}
        {contact.linkedin_url && (
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            LinkedIn <ExternalLink className="size-3" />
          </a>
        )}
      </div>

      {contact.draft_message && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Draft message
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1.5 px-2 text-xs"
              onClick={() => copy(contact.draft_message!, 'message')}
            >
              {copied === 'message' ? <Check className="size-3" /> : <Copy className="size-3" />}
              Copy
            </Button>
          </div>
          <p className="whitespace-pre-line rounded-md bg-muted/40 p-3 text-sm leading-relaxed text-muted-foreground">
            {contact.draft_message}
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => updateStatus(opt.value)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              status === opt.value
                ? getContactStatusColor(opt.value)
                : 'border-border bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
