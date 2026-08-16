import { useMemo, useState } from 'react'

import type { ResultSet } from '@/api/types'
import { Icon } from '@/components/icons'

const PAGE_SIZE = 25

type SortState = { column: number; direction: 'asc' | 'desc' } | null

function compare(a: unknown, b: unknown): number {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

function format(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

export function ResultTable({ result }: { result: ResultSet }) {
  const [sort, setSort] = useState<SortState>(null)
  const [page, setPage] = useState(0)

  const rows = useMemo(() => {
    if (!sort) return result.rows
    const sorted = [...result.rows].sort((a, b) => compare(a[sort.column], b[sort.column]))
    return sort.direction === 'desc' ? sorted.reverse() : sorted
  }, [result.rows, sort])

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  function toggleSort(column: number) {
    setPage(0)
    setSort((current) =>
      current?.column === column
        ? current.direction === 'asc'
          ? { column, direction: 'desc' }
          : null
        : { column, direction: 'asc' },
    )
  }

  if (result.row_count === 0) {
    return (
      <div className="rounded-md border border-subtle bg-surface-bg px-4 py-6 text-center">
        <p className="text-body-md text-on-surface-variant">
          The query ran successfully and returned no rows.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-md border border-subtle">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead className="border-b border-subtle bg-surface-bg">
            <tr>
              {result.columns.map((column, index) => (
                <th key={column} className="p-0">
                  <button
                    onClick={() => toggleSort(index)}
                    className="flex w-full items-center gap-1 px-3 py-2.5 text-label-md uppercase tracking-wider text-on-surface-variant transition-colors hover:text-on-surface"
                  >
                    {column}
                    {sort?.column === index && (
                      <Icon
                        name={sort.direction === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                        size={12}
                      />
                    )}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle text-body-md text-on-surface">
            {visible.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="zebra-row transition-colors hover:bg-surface-container-low"
              >
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={`px-3 py-2 ${
                      typeof cell === 'number'
                        ? 'text-right font-mono tabular-nums'
                        : ''
                    } ${cell === null ? 'text-outline' : ''}`}
                  >
                    {format(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-subtle bg-surface px-3 py-2 text-label-md text-on-surface-variant">
        <span>
          {rows.length === 0
            ? 'No rows'
            : `Showing ${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, rows.length)} of ${rows.length.toLocaleString()}`}
          {result.truncated && (
            <span className="ml-2 text-data-amber">
              · capped, more rows exist
            </span>
          )}
          <span className="ml-2 font-mono normal-case tracking-normal text-outline">
            {Math.round(result.duration_ms)} ms
          </span>
        </span>

        {pageCount > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              aria-label="Previous page"
              className="rounded p-1 transition-colors hover:bg-surface-container-high disabled:opacity-40"
            >
              <Icon name="chevron_left" size={16} />
            </button>
            <span className="tabular-nums">
              {page + 1} / {pageCount}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={page >= pageCount - 1}
              aria-label="Next page"
              className="rounded p-1 transition-colors hover:bg-surface-container-high disabled:opacity-40"
            >
              <Icon name="chevron_right" size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
