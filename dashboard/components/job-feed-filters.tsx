'use client'

import { cn } from '@/lib/utils'

const nativeSelectClass = cn(
  'h-8 min-w-[9.5rem] cursor-pointer rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm',
  'text-foreground shadow-none transition-colors outline-none',
  'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50',
  'disabled:cursor-not-allowed disabled:opacity-50',
  'dark:bg-input/30'
)

export function HiddenFilters({
  current,
  skip,
}: {
  current: Record<string, string | undefined>
  skip: string
}) {
  return (
    <>
      {Object.entries(current)
        .filter(([k, v]) => k !== skip && v)
        .map(([k, v]) => (
          <input key={k} type="hidden" name={k} value={v} />
        ))}
    </>
  )
}

export function FilterSelect({
  label,
  name,
  value,
  current,
  options,
}: {
  label: string
  name: string
  value: string
  current: Record<string, string | undefined>
  options: { value: string; label: string }[]
}) {
  return (
    <form method="GET" className="flex items-center gap-2">
      <HiddenFilters current={current} skip={name} />
      <label className="whitespace-nowrap text-xs font-medium text-muted-foreground">{label}</label>
      <select
        name={name}
        defaultValue={value}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className={nativeSelectClass}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <noscript>
        <button type="submit" className="h-8 rounded-lg bg-primary px-2 text-xs font-medium text-primary-foreground">
          Go
        </button>
      </noscript>
    </form>
  )
}
