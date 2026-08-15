import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { fetchSchema } from '@/api/connections'
import type { SchemaColumn, SchemaTable } from '@/api/types'
import { Icon } from '@/components/icons'
import { SearchInput, Skeleton, Tag } from '@/components/ui'

/** Browse the indexed schema: tables, columns, keys, and join paths. */
export function SchemaExplorer({ connectionId }: { connectionId: string }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['schema', connectionId],
    queryFn: () => fetchSchema(connectionId),
    retry: false,
  })

  const tables = useMemo(() => {
    if (!data) return []
    const needle = filter.trim().toLowerCase()
    if (!needle) return data.tables
    return data.tables.filter(
      (t) =>
        t.table_name.toLowerCase().includes(needle) ||
        t.columns.some((c) => c.column_name.toLowerCase().includes(needle)),
    )
  }, [data, filter])

  if (isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-72 rounded-lg" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <p className="text-body-md text-on-surface-variant">
        {errorMessage(error, 'Schema is not available yet.')}
      </p>
    )
  }

  const active = tables.find((t) => t.table_name === selected) ?? tables[0] ?? null

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-subtle bg-subtle sm:grid-cols-4">
        <Metric icon="table" label="Tables" value={data.table_count} />
        <Metric icon="view_column" label="Columns" value={data.column_count} />
        <Metric icon="link" label="Join paths" value={data.edges.length} />
        <Metric
          icon="link_off"
          label="Unlinked"
          value={data.isolated_tables.length}
          hint={data.isolated_tables.join(', ')}
          warn={data.isolated_tables.length > 0}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-[minmax(0,16rem)_1fr]">
        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-subtle bg-surface-container-lowest">
          <div className="border-b border-subtle p-2">
            <SearchInput
              icon="filter_list"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter tables…"
              className="border-transparent bg-surface-bg py-1.5"
            />
          </div>

          <ul className="max-h-[26rem] overflow-y-auto p-1.5">
            {tables.length === 0 && (
              <li className="px-3 py-8 text-center text-body-md text-outline">
                No matching tables
              </li>
            )}
            {tables.map((table) => {
              const isActive = active?.table_name === table.table_name
              return (
                <li key={table.id}>
                  <button
                    onClick={() => setSelected(table.table_name)}
                    className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors ${
                      isActive
                        ? 'bg-secondary-container text-on-secondary-container'
                        : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
                    }`}
                  >
                    <Icon name="table_rows" size={16} fill={isActive} />
                    <span className="min-w-0 flex-1 truncate font-mono text-code-sm">
                      {table.table_name}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-outline">
                      {table.columns.length}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        {active && <TableDetail table={active} />}
      </div>
    </div>
  )
}

function Metric({
  icon,
  label,
  value,
  hint,
  warn,
}: {
  icon: string
  label: string
  value: number
  hint?: string
  warn?: boolean
}) {
  return (
    <div className="bg-surface-container-lowest px-4 py-3" title={hint || undefined}>
      <div className="flex items-center gap-1.5 text-label-md uppercase tracking-wider text-on-surface-variant">
        <Icon name={icon} size={14} />
        {label}
      </div>
      <p
        className={`mt-1 text-headline-sm tabular-nums ${warn ? 'text-data-amber' : 'text-primary'}`}
      >
        {value.toLocaleString()}
      </p>
    </div>
  )
}

function TableDetail({ table }: { table: SchemaTable }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-subtle bg-surface-container-lowest">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle bg-surface-bg px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon name="table" size={18} className="text-on-surface-variant" />
          <h4 className="font-mono text-code-sm font-medium text-primary">
            {table.table_name}
          </h4>
        </div>
        {table.row_estimate !== null && (
          <span className="font-mono text-[11px] tabular-nums text-on-surface-variant">
            ~{table.row_estimate.toLocaleString()} rows
          </span>
        )}
      </div>

      <div className="max-h-80 overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 border-b border-subtle bg-surface-bg text-label-md uppercase tracking-wider text-on-surface-variant">
            <tr>
              <th className="px-4 py-2.5 font-semibold">Column</th>
              <th className="px-3 py-2.5 font-semibold">Type</th>
              <th className="px-3 py-2.5 font-semibold">Notes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle text-body-md text-on-surface">
            {table.columns.map((column) => (
              <ColumnRow key={column.column_name} column={column} />
            ))}
          </tbody>
        </table>
      </div>

      <details className="group border-t border-subtle bg-surface-bg">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 px-4 py-2.5 text-label-md text-on-surface-variant transition-colors hover:text-on-surface">
          <Icon
            name="chevron_right"
            size={16}
            className="transition-transform group-open:rotate-90"
          />
          Indexed description — the text retrieval searches
        </summary>
        <p className="mx-4 mb-4 rounded-md border border-subtle bg-surface-container-lowest p-3 text-code-sm leading-relaxed text-on-surface-variant">
          {table.description}
        </p>
      </details>
    </div>
  )
}

function ColumnRow({ column }: { column: SchemaColumn }) {
  return (
    <tr className="zebra-row transition-colors hover:bg-surface-container-low">
      <td className="px-4 py-2 font-mono text-code-sm">{column.column_name}</td>
      <td className="px-3 py-2 font-mono text-[11px] lowercase text-on-surface-variant">
        {column.data_type}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {column.is_pk && (
            <Tag tone="indigo">
              <Icon name="key" size={12} />
              PK
            </Tag>
          )}
          {column.fk_target && (
            <Tag tone="indigo">
              <Icon name="link" size={12} />
              {column.fk_target}
            </Tag>
          )}
          {column.is_indexed && !column.is_pk && <Tag>indexed</Tag>}
          {!column.is_nullable && <Tag>not null</Tag>}
          {column.sample_values && (
            <span className="font-mono text-[11px] text-outline">
              {column.sample_values.slice(0, 4).join(' · ')}
              {column.sample_values.length > 4 && ' …'}
            </span>
          )}
        </div>
      </td>
    </tr>
  )
}
