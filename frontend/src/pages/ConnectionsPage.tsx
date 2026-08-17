import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import {
  deleteConnection,
  indexConnection,
  listConnections,
  testConnection,
} from '@/api/connections'
import type {
  Connection,
  ConnectionStatus,
  ConnectionTestResult,
  Dialect,
  IndexResult,
} from '@/api/types'
import { AddConnectionDialog } from '@/components/AddConnectionForm'
import { SchemaExplorer } from '@/components/SchemaExplorer'
import { Icon } from '@/components/icons'
import { Button, EmptyState, Pill, Skeleton } from '@/components/ui'

/** Per-dialect card iconography, matching the design's tinted icon tiles. */
const DIALECT_STYLE: Record<Dialect, { icon: string; tile: string; label: string }> = {
  postgres: {
    icon: 'storage',
    tile: 'bg-secondary-container text-on-secondary-container',
    label: 'PostgreSQL',
  },
  mysql: {
    icon: 'dns',
    tile: 'bg-data-amber/10 text-data-amber',
    label: 'MySQL',
  },
  sqlite: {
    icon: 'database',
    tile: 'bg-data-indigo/10 text-data-indigo',
    label: 'SQLite',
  },
}

const STATUS: Record<
  ConnectionStatus,
  { tone: 'online' | 'offline' | 'pending' | 'amber'; label: string }
> = {
  indexed: { tone: 'online', label: 'Indexed' },
  connected: { tone: 'pending', label: 'Connected' },
  indexing: { tone: 'amber', label: 'Indexing' },
  pending: { tone: 'pending', label: 'Not tested' },
  failed: { tone: 'offline', label: 'Offline' },
}

export function ConnectionsPage() {
  const [adding, setAdding] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: connections, isPending } = useQuery({
    queryKey: ['connections'],
    queryFn: listConnections,
  })

  const active = connections?.find((c) => c.id === expanded) ?? null

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-2 text-headline-lg-mobile text-primary md:text-headline-lg">
          Data Connections
        </h2>
        <p className="max-w-2xl text-body-lg text-on-surface-variant">
          Manage your database connections. The semantic engine needs an active schema
          index before it can answer natural-language questions against a source.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <button
          onClick={() => setAdding(true)}
          className="group relative flex min-h-[220px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-subtle bg-surface-container-lowest shadow-card transition-shadow duration-200 hover:border-primary hover:shadow-card-hover"
        >
          <div className="absolute inset-0 bg-secondary-container opacity-0 transition-opacity group-hover:opacity-10" />
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-container-low text-on-surface-variant transition-colors group-hover:bg-primary-fixed group-hover:text-primary">
            <Icon name="add" size={24} />
          </div>
          <span className="text-headline-sm text-primary">Add Connection</span>
          <span className="mt-1 text-body-md text-on-surface-variant">
            PostgreSQL, MySQL, SQLite…
          </span>
        </button>

        {isPending && (
          <>
            <Skeleton className="h-[220px] rounded-xl" />
            <Skeleton className="h-[220px] rounded-xl" />
          </>
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

        {connections?.length === 0 && !isPending && (
          <div className="md:col-span-1 lg:col-span-2 xl:col-span-3">
            <EmptyState
              icon="cloud_off"
              title="No connections yet"
              description="Point the platform at a database to introspect and index its schema."
            />
          </div>
        )}
      </div>

      {active?.status === 'indexed' && (
        <section className="mt-8 animate-fade-in rounded-xl border border-subtle bg-surface-container-lowest shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-5 py-4">
            <div className="flex items-center gap-2">
              <Icon name="schema" size={20} className="text-on-surface-variant" />
              <h3 className="text-headline-sm text-primary">
                {active.name} - indexed schema
              </h3>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setExpanded(null)}>
              Close
            </Button>
          </div>
          <div className="p-5">
            <SchemaExplorer connectionId={active.id} />
          </div>
        </section>
      )}

      {adding && <AddConnectionDialog onClose={() => setAdding(false)} />}
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
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['connections'] })

  const test = useMutation({
    mutationFn: () => testConnection(connection.id),
    onSuccess: (result) => {
      setTestResult(result)
      setActionError(null)
      refresh()
    },
    onError: (err) => setActionError(errorMessage(err)),
  })

  const index = useMutation({
    mutationFn: () => indexConnection(connection.id),
    onSuccess: (result) => {
      setIndexResult(result)
      setActionError(null)
      refresh()
      queryClient.invalidateQueries({ queryKey: ['schema', connection.id] })
    },
    onError: (err) => setActionError(errorMessage(err, 'Indexing failed')),
  })

  const remove = useMutation({
    mutationFn: () => deleteConnection(connection.id),
    onSuccess: refresh,
    onError: (err) => setActionError(errorMessage(err)),
  })

  const style = DIALECT_STYLE[connection.dialect]
  const status = STATUS[connection.status]
  const failed = connection.status === 'failed'

  const subtitle = testResult?.server_version
    ? `${style.label} ${testResult.server_version}`
    : style.label

  const location =
    connection.dialect === 'sqlite'
      ? connection.database.split(/[\\/]/).pop()
      : `${connection.host}:${connection.port}/${connection.database}`

  // min-h rather than a fixed h: the status line grows when a test or an index
  // run reports back, and a fixed height pushed that overflow straight out
  // through the bottom of the card.
  return (
    <div
      className={`flex min-h-[220px] flex-col rounded-xl border bg-surface-container-lowest p-5 shadow-card transition-shadow hover:shadow-card-hover ${
        failed ? 'border-error-container' : 'border-subtle'
      }`}
    >
      <div className="mb-4 flex items-start justify-between">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded ${style.tile}`}
        >
          <Icon name={style.icon} size={20} />
        </div>
        <Pill tone={status.tone}>{status.label}</Pill>
      </div>

      <h3 className="mb-1 truncate text-headline-sm text-primary" title={connection.name}>
        {connection.name}
      </h3>
      <p className="truncate text-body-md text-on-surface-variant" title={location}>
        {subtitle}
      </p>
      <p className="mt-0.5 truncate font-mono text-[11px] text-outline" title={location}>
        {location}
      </p>

      <div className="mt-auto flex items-center gap-1.5 pt-3">
        <CardAction
          icon="cable"
          label="Test connection"
          onClick={() => test.mutate()}
          busy={test.isPending}
        />
        <CardAction
          icon="sync"
          label={connection.status === 'indexed' ? 'Re-index schema' : 'Index schema'}
          onClick={() => index.mutate()}
          busy={index.isPending}
        />
        {connection.status === 'indexed' && (
          <CardAction
            icon={expanded ? 'visibility_off' : 'schema'}
            label={expanded ? 'Hide schema' : 'Browse schema'}
            onClick={onToggle}
            active={expanded}
          />
        )}
        <CardAction
          icon="delete"
          label="Delete connection"
          onClick={() => remove.mutate()}
          busy={remove.isPending}
          danger
        />
      </div>

      <div className="mt-3 border-t border-subtle pt-3 text-body-md">
        <StatusLine
          connection={connection}
          testResult={testResult}
          indexResult={indexResult}
          error={actionError}
        />
      </div>
    </div>
  )
}

function StatusLine({
  connection,
  testResult,
  indexResult,
  error,
}: {
  connection: Connection
  testResult: ConnectionTestResult | null
  indexResult: IndexResult | null
  error: string | null
}) {
  if (error || (connection.status === 'failed' && connection.last_error)) {
    return (
      <p
        className="flex items-center gap-1 truncate text-[12px] text-error"
        title={error ?? connection.last_error ?? ''}
      >
        <Icon name="warning" size={14} />
        {error ?? 'Connection failed'}
      </p>
    )
  }

  if (indexResult) {
    return (
      <p className="flex items-center gap-1 truncate text-[12px] text-on-surface-variant">
        <Icon name="check_circle" size={14} className="text-sql-syntax-string" />
        {indexResult.tables_indexed} tables · {indexResult.columns_indexed} columns ·{' '}
        {indexResult.foreign_keys} FKs
      </p>
    )
  }

  if (testResult?.ok) {
    return (
      <p className="flex items-center gap-1 truncate text-[12px] text-on-surface-variant">
        <Icon name="bolt" size={14} className="text-sql-syntax-string" />
        Reachable in {testResult.latency_ms} ms
      </p>
    )
  }

  if (connection.last_indexed_at) {
    return (
      <p className="flex items-center gap-1 truncate text-[12px] text-on-surface-variant">
        <Icon name="sync" size={14} />
        Indexed {relativeTime(connection.last_indexed_at)}
      </p>
    )
  }

  return (
    <p className="flex items-center gap-1 truncate text-[12px] text-outline">
      <Icon name="pending" size={14} />
      Not indexed yet
    </p>
  )
}

function CardAction({
  icon,
  label,
  onClick,
  busy,
  danger,
  active,
}: {
  icon: string
  label: string
  onClick: () => void
  busy?: boolean
  danger?: boolean
  active?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={label}
      aria-label={label}
      className={`flex h-8 w-8 items-center justify-center rounded-md border border-subtle transition-colors disabled:opacity-40 ${
        active
          ? 'bg-secondary-container text-on-secondary-container'
          : danger
            ? 'text-on-surface-variant hover:bg-error-container hover:text-error'
            : 'text-on-surface-variant hover:bg-surface-container-high hover:text-primary'
      }`}
    >
      {busy ? (
        <Icon name="progress_activity" size={16} className="animate-spin" />
      ) : (
        <Icon name={icon} size={16} />
      )}
    </button>
  )
}

/** "2m ago" / "3h ago" / "5d ago" - the design shows relative index times. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'recently'

  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
