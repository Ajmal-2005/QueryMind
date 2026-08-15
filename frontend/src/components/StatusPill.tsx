import type { ConnectionStatus } from '@/api/types'

const STYLES: Record<ConnectionStatus, string> = {
  pending: 'bg-slate-100 text-slate-600 ring-slate-200',
  connected: 'bg-sky-50 text-sky-700 ring-sky-200',
  indexing: 'bg-amber-50 text-amber-700 ring-amber-200',
  indexed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-rose-50 text-rose-700 ring-rose-200',
}

const LABELS: Record<ConnectionStatus, string> = {
  pending: 'Not tested',
  connected: 'Connected',
  indexing: 'Indexing…',
  indexed: 'Indexed',
  failed: 'Failed',
}

export function StatusPill({ status }: { status: ConnectionStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  )
}
