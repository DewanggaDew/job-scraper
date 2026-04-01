'use client'

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
    <form method="GET" className="flex items-center gap-1.5">
      <HiddenFilters current={current} skip={name} />
      <label className="text-xs text-gray-500 font-medium whitespace-nowrap">{label}</label>
      <select
        name={name}
        defaultValue={value}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className="border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 bg-white cursor-pointer"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <noscript>
        <button type="submit" className="px-2 py-1.5 text-xs bg-green-600 text-white rounded-md">
          Go
        </button>
      </noscript>
    </form>
  )
}
