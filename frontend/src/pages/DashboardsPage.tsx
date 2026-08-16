/** Saved dashboards (F18).
 *
 *  One page, two states: the list, and one dashboard opened. Opening refreshes
 *  — nothing is precomputed, because a dashboard quietly showing last week's
 *  numbers is worse than no dashboard at all.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import {
  createDashboard,
  deleteDashboard,
  deleteTile,
  getDashboard,
  listDashboards,
  refreshDashboard,
} from '@/api/dashboards'
import type { DashboardTile, TileResult } from '@/api/types'
import { ChartView } from '@/components/ChartView'
import { Icon } from '@/components/icons'
import { Alert, Button, EmptyState, Input, Pill, Skeleton } from '@/components/ui'

export function DashboardsPage() {
  const [openId, setOpenId] = useState<string | null>(null)
  return openId ? (
    <DashboardDetailView id={openId} onBack={() => setOpenId(null)} />
  ) : (
    <DashboardList onOpen={setOpenId} />
  )
}

/* ------------------------------------------------------------------- list */

function DashboardList({ onOpen }: { onOpen: (id: string) => void }) {
  const [name, setName] = useState('')
  const queryClient = useQueryClient()

  const { data, isPending, error } = useQuery({
    queryKey: ['dashboards'],
    queryFn: listDashboards,
  })

  const create = useMutation({
    mutationFn: () => createDashboard({ name: name.trim() }),
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
    },
  })

  const remove = useMutation({
    mutationFn: deleteDashboard,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboards'] }),
  })

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="mb-2 text-headline-lg-mobile text-primary md:text-headline-lg">
            Dashboards
          </h2>
          <p className="max-w-2xl text-body-lg text-on-surface-variant">
            Pinned queries, re-run each time you open them.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate()
          }}
          className="flex gap-2"
        >
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New dashboard name"
            className="min-w-[14rem]"
          />
          <Button
            type="submit"
            variant="primary"
            icon="add"
            disabled={!name.trim()}
            busy={create.isPending}
          >
            Create
          </Button>
        </form>
      </div>

      {error && <Alert>{errorMessage(error, 'Could not load dashboards')}</Alert>}

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-28" />
          ))}
        </div>
      ) : data && data.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((dashboard) => (
            <div
              key={dashboard.id}
              className="group rounded-xl border border-subtle bg-surface-container-lowest p-4 shadow-card transition-colors hover:border-primary"
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <button
                  onClick={() => onOpen(dashboard.id)}
                  className="min-w-0 flex-1 text-left"
                >
                  <h3 className="truncate text-headline-sm text-primary">
                    {dashboard.name}
                  </h3>
                </button>
                <button
                  onClick={() => remove.mutate(dashboard.id)}
                  aria-label={`Delete ${dashboard.name}`}
                  className="shrink-0 rounded p-1 text-outline opacity-0 transition-opacity hover:bg-error-container hover:text-error group-hover:opacity-100"
                >
                  <Icon name="delete" size={16} />
                </button>
              </div>

              {dashboard.description && (
                <p className="mb-2 line-clamp-2 text-body-md text-on-surface-variant">
                  {dashboard.description}
                </p>
              )}

              <div className="flex items-center justify-between">
                <Pill tone="indigo" dot={false}>
                  {dashboard.tile_count} tile
                  {dashboard.tile_count === 1 ? '' : 's'}
                </Pill>
                <button
                  onClick={() => onOpen(dashboard.id)}
                  className="flex items-center gap-1 text-label-md text-on-surface-variant transition-colors hover:text-primary"
                >
                  Open <Icon name="chevron_right" size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon="dashboard"
          title="No dashboards yet"
          description="Ask a question, then use Pin on the result to save it here."
        />
      )}
    </div>
  )
}

/* ----------------------------------------------------------------- detail */

function DashboardDetailView({
  id,
  onBack,
}: {
  id: string
  onBack: () => void
}) {
  const queryClient = useQueryClient()

  const { data: dashboard } = useQuery({
    queryKey: ['dashboard', id],
    queryFn: () => getDashboard(id),
  })

  // Fires on open, not on a button — the tiles are only worth showing fresh.
  const {
    data: refresh,
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: ['dashboard-refresh', id],
    queryFn: () => refreshDashboard(id),
    refetchOnWindowFocus: false,
  })

  const remove = useMutation({
    mutationFn: (tileId: string) => deleteTile(id, tileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-refresh', id] })
    },
  })

  const byTile = new Map<string, TileResult>(
    (refresh?.tiles ?? []).map((tile) => [tile.tile_id, tile]),
  )

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <button
            onClick={onBack}
            className="mb-1 flex items-center gap-1 text-label-md text-on-surface-variant transition-colors hover:text-primary"
          >
            <Icon name="chevron_left" size={16} />
            All dashboards
          </button>
          <h2 className="text-headline-lg-mobile text-primary md:text-headline-lg">
            {dashboard?.name ?? '…'}
          </h2>
          {refresh && (
            <p className="mt-1 text-body-md text-on-surface-variant">
              Refreshed {new Date(refresh.refreshed_at).toLocaleTimeString()} ·{' '}
              {Math.round(refresh.duration_ms)} ms
            </p>
          )}
        </div>

        <Button icon="refresh" busy={isFetching} onClick={() => refetch()}>
          Refresh
        </Button>
      </div>

      {error && <Alert>{errorMessage(error, 'Could not refresh this dashboard')}</Alert>}

      {dashboard?.tiles.length === 0 && (
        <EmptyState
          icon="push_pin"
          title="Nothing pinned yet"
          description="Ask a question, then use Pin on the result to add it here."
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {dashboard?.tiles.map((tile) => (
          <TileCard
            key={tile.id}
            tile={tile}
            result={byTile.get(tile.id)}
            loading={isFetching && !byTile.has(tile.id)}
            onRemove={() => remove.mutate(tile.id)}
          />
        ))}
      </div>
    </div>
  )
}

function TileCard({
  tile,
  result,
  loading,
  onRemove,
}: {
  tile: DashboardTile
  result?: TileResult
  loading: boolean
  onRemove: () => void
}) {
  // The chart the user pinned wins over a freshly derived one, so a tile keeps
  // whatever override they chose at the time.
  const spec =
    (tile.chart && tile.chart.type ? (tile.chart as never) : null) ??
    result?.chart ??
    result?.analysis?.chart

  return (
    <div className="group rounded-xl border border-subtle bg-surface-container-lowest p-4 shadow-card">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-label-md text-on-surface">{tile.title}</h3>
          <p className="truncate text-[11px] text-outline">
            {tile.connection_name ?? 'database removed'}
            {result?.cached && ' · cached'}
          </p>
        </div>
        <button
          onClick={onRemove}
          aria-label={`Remove ${tile.title}`}
          className="shrink-0 rounded p-1 text-outline opacity-0 transition-opacity hover:bg-error-container hover:text-error group-hover:opacity-100"
        >
          <Icon name="close" size={16} />
        </button>
      </div>

      {loading && <Skeleton className="h-56" />}

      {!loading && result && !result.ok && (
        <div className="rounded-md border border-error/25 bg-error-container p-3">
          <p className="text-body-md text-error">{result.error}</p>
        </div>
      )}

      {!loading && result?.ok && result.result && spec && (
        <ChartView result={result.result} spec={spec} analysis={result.analysis ?? undefined} height={240} />
      )}
    </div>
  )
}
