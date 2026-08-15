import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchSchema } from '@/api/connections'
import { errorMessage } from '@/api/client'
import type { SchemaColumn, SchemaTable } from '@/api/types'

/** Browse the indexed schema: tables, columns, keys, and join paths. */
export function SchemaExplorer({ connectionId }: { connectionId: string }) {
  const [selected, setSelected] = useState<string | null>(null)

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['schema', connectionId],
    queryFn: () => fetchSchema(connectionId),
    retry: false,
  })

  if (isPending) {
    return <p className="text-sm text-slate-500">Loading schema…</p>
  }

  if (isError || !data) {
    return (
      <p className="text-sm text-slate-500">
        {errorMessage(error, 'Schema is not available yet.')}
      </p>
    )
  }

  const active =
    data.tables.find((t) => t.table_name === selected) ?? data.tables[0] ?? null

  return (
    <div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-500">
        <span>
          <strong className="text-slate-900">{data.table_count}</strong> tables
        </span>
        <span>
          <strong className="text-slate-900">{data.column_count}</strong> columns
        </span>
        <span>
          <strong className="text-slate-900">{data.edges.length}</strong> join paths
        </span>
        {data.isolated_tables.length > 0 && (
          <span title={data.isolated_tables.join(', ')}>
            <strong className="text-slate-900">{data.isolated_tables.length}</strong>{' '}
            unlinked
          </span>
        )}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,14rem)_1fr]">
        <ul className="max-h-96 overflow-y-auto rounded-lg border border-slate-200 bg-white">
          {data.tables.map((table) => (
            <li key={table.id}>
              <button
                onClick={() => setSelected(table.table_name)}
                className={`flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                  active?.table_name === table.table_name
                    ? 'bg-slate-100 font-medium'
                    : ''
                }`}
              >
                <span className="font-mono">{table.table_name}</span>
                <span className="shrink-0 text-xs text-slate-400">
                  {table.columns.length}c
                </span>
              </button>
            </li>
          ))}
        </ul>

        {active && <TableDetail table={active} />}
      </div>
    </div>
  )
}

function TableDetail({ table }: { table: SchemaTable }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-mono text-sm font-semibold">{table.table_name}</h3>
        {table.row_estimate !== null && (
          <span className="text-xs text-slate-400">
            ~{table.row_estimate.toLocaleString()} rows
          </span>
        )}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
              <th className="py-1.5 pr-3 font-medium">Column</th>
              <th className="py-1.5 pr-3 font-medium">Type</th>
              <th className="py-1.5 font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {table.columns.map((column) => (
              <ColumnRow key={column.column_name} column={column} />
            ))}
          </tbody>
        </table>
      </div>

      <details className="mt-4">
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-800">
          Indexed description — this is the text retrieval searches
        </summary>
        <p className="mt-2 rounded bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
          {table.description}
        </p>
      </details>
    </div>
  )
}

function ColumnRow({ column }: { column: SchemaColumn }) {
  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="py-1.5 pr-3 font-mono text-xs">{column.column_name}</td>
      <td className="py-1.5 pr-3 text-xs text-slate-500">{column.data_type}</td>
      <td className="py-1.5 text-xs text-slate-500">
        <span className="flex flex-wrap items-center gap-1.5">
          {column.is_pk && <Tag className="bg-violet-50 text-violet-700">PK</Tag>}
          {column.fk_target && (
            <Tag className="bg-sky-50 text-sky-700">→ {column.fk_target}</Tag>
          )}
          {column.is_indexed && !column.is_pk && (
            <Tag className="bg-slate-100 text-slate-600">indexed</Tag>
          )}
          {!column.is_nullable && (
            <Tag className="bg-slate-100 text-slate-600">not null</Tag>
          )}
          {column.sample_values && (
            <span className="text-slate-400">
              {column.sample_values.slice(0, 4).join(' · ')}
              {column.sample_values.length > 4 && ' …'}
            </span>
          )}
        </span>
      </td>
    </tr>
  )
}

function Tag({
  children,
  className,
}: {
  children: React.ReactNode
  className: string
}) {
  return (
    <span className={`rounded px-1.5 py-0.5 font-medium ${className}`}>{children}</span>
  )
}
