import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import {
  deleteConnection,
  indexConnection,
  listConnections,
  testConnection,
} from '@/api/connections'
import type { Connection, ConnectionTestResult, IndexResult } from '@/api/types'
import { AddConnectionForm } from '@/components/AddConnectionForm'
import { SchemaExplorer } from '@/components/SchemaExplorer'
import { StatusPill } from '@/components/StatusPill'

export function ConnectionsPage() {
  const [adding, setAdding] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: connections, isPending } = useQuery({
    queryKey: ['connections'],
    queryFn: listConnections,
  })

  return (
    <div>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Database connections</h2>
          <p className="text-sm text-slate-500">
            Connect a database, then index its schema so questions can be answered
            against it.
          </p>
        </div>
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            className="shrink-0 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Add connection
          </button>
        )}
      </div>

      {adding && (
        <div className="mt-5">
          <AddConnectionForm onDone={() => setAdding(false)} />
        </div>
      )}

      <div className="mt-5 space-y-3">
        {isPending && <p className="text-sm text-slate-500">Loading…</p>}

        {connections?.length === 0 && !adding && (
          <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
            No connections yet. Add one to get started.
          </p>
        )}

        {connections?.map((connection) => (
          <ConnectionCard
            key={connection.id}
            connection={connection}
            expanded={expanded === connection.id}
            onToggle={() =>
              setExpanded(expanded === connection.id ? null : connection.id)
            }
          />
        ))}
      </div>
    </div>
  )
}

interface CardProps {
  connection: Connection
  expanded: boolean
  onToggle: () => void
}

function ConnectionCard({ connection, expanded, onToggle }: CardProps) {
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null)
  const [indexResult, setIndexResult] = useState<IndexResult | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const queryClient = useQueryClient()

  function refreshConnections() {
    queryClient.invalidateQueries({ queryKey: ['connections'] })
  }

  const test = useMutation({
    mutationFn: () => testConnection(connection.id),
    onSuccess: (result) => {
      setTestResult(result)
      setActionError(null)
      refreshConnections()
    },
    onError: (err) => setActionError(errorMessage(err)),
  })

  const index = useMutation({
    mutationFn: () => indexConnection(connection.id),
    onSuccess: (result) => {
      setIndexResult(result)
      setActionError(null)
      refreshConnections()
      queryClient.invalidateQueries({ queryKey: ['schema', connection.id] })
    },
    onError: (err) => setActionError(errorMessage(err, 'Indexing failed')),
  })

  const remove = useMutation({
    mutationFn: () => deleteConnection(connection.id),
    onSuccess: refreshConnections,
    onError: (err) => setActionError(errorMessage(err)),
  })

  const location =
    connection.dialect === 'sqlite'
      ? connection.database
      : `${connection.host}:${connection.port}/${connection.database}`

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium">{connection.name}</h3>
            <StatusPill status={connection.status} />
          </div>
          <p className="mt-0.5 truncate font-mono text-xs text-slate-500">
            {connection.dialect} · {location}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          <Action onClick={() => test.mutate()} busy={test.isPending} label="Test" />
          <Action
            onClick={() => index.mutate()}
            busy={index.isPending}
            label={connection.status === 'indexed' ? 'Re-index' : 'Index schema'}
            primary
          />
          {connection.status === 'indexed' && (
            <Action
              onClick={onToggle}
              label={expanded ? 'Hide schema' : 'View schema'}
            />
          )}
          <Action
            onClick={() => remove.mutate()}
            busy={remove.isPending}
            label="Delete"
            danger
          />
        </div>
      </div>

      {testResult && (
        <p
          className={`mt-3 text-sm ${testResult.ok ? 'text-emerald-700' : 'text-rose-600'}`}
        >
          {testResult.ok
            ? `Connected in ${testResult.latency_ms} ms · server ${testResult.server_version}`
            : testResult.error}
        </p>
      )}

      {indexResult && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-600">
          <Stat label="tables" value={indexResult.tables_indexed} />
          <Stat label="columns" value={indexResult.columns_indexed} />
          <Stat label="foreign keys" value={indexResult.foreign_keys} />
          <Stat label="unlinked" value={indexResult.isolated_tables} />
          <Stat label="ms" value={Math.round(indexResult.total_ms)} />
          <span className="text-slate-400">via {indexResult.embedder}</span>
        </dl>
      )}

      {(actionError || connection.last_error) && (
        <p role="alert" className="mt-3 break-words text-sm text-rose-600">
          {actionError ?? connection.last_error}
        </p>
      )}

      {expanded && (
        <div className="mt-5 border-t border-slate-200 pt-5">
          <SchemaExplorer connectionId={connection.id} />
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <strong className="text-slate-900">{value.toLocaleString()}</strong>{' '}
      <span className="text-slate-500">{label}</span>
    </span>
  )
}

interface ActionProps {
  onClick: () => void
  label: string
  busy?: boolean
  primary?: boolean
  danger?: boolean
}

function Action({ onClick, label, busy, primary, danger }: ActionProps) {
  const tone = primary
    ? 'bg-slate-900 text-white hover:bg-slate-700 border-slate-900'
    : danger
      ? 'border-slate-300 text-rose-600 hover:bg-rose-50'
      : 'border-slate-300 text-slate-700 hover:bg-slate-100'

  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={`rounded-lg border px-3 py-1.5 text-sm transition disabled:opacity-50 ${tone}`}
    >
      {busy ? 'Working…' : label}
    </button>
  )
}
