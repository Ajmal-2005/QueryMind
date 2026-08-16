/** Pin a result to a dashboard (F18).
 *
 *  What gets stored is the SQL, not the question. Re-asking the question on
 *  every dashboard open would re-run generation, cost tokens each time, and
 *  could return a different query than the one the user chose to pin.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { addTile, createDashboard, listDashboards } from '@/api/dashboards'
import type { ChartSpec } from '@/api/types'
import { Icon } from '@/components/icons'
import { Button, Input, Spinner } from '@/components/ui'

export function PinToDashboard({
  connectionId,
  sql,
  question,
  queryId,
  chart,
}: {
  connectionId: string
  sql: string
  question: string
  queryId?: string | null
  chart?: ChartSpec
}) {
  const [open, setOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [pinned, setPinned] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: dashboards, isPending } = useQuery({
    queryKey: ['dashboards'],
    queryFn: listDashboards,
    enabled: open,
  })

  const pin = useMutation({
    mutationFn: async (dashboardId: string) =>
      addTile(dashboardId, {
        title: question.slice(0, 80) || 'Saved query',
        connection_id: connectionId,
        sql,
        question,
        query_id: queryId ?? null,
        // The chart the user is actually looking at, including any override.
        chart: chart ? { ...chart } : {},
      }),
    onSuccess: (_tile, dashboardId) => {
      const name =
        dashboards?.find((d) => d.id === dashboardId)?.name ?? 'the dashboard'
      setPinned(name)
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
    },
    onError: (err) => setError(errorMessage(err, 'Could not pin this query')),
  })

  const create = useMutation({
    mutationFn: () => createDashboard({ name: newName.trim() }),
    onSuccess: (dashboard) => {
      setNewName('')
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      pin.mutate(dashboard.id)
    },
    onError: (err) => setError(errorMessage(err, 'Could not create the dashboard')),
  })

  if (pinned) {
    return (
      <span className="flex items-center gap-1.5 text-label-md text-sql-syntax-string">
        <Icon name="check_circle" size={16} fill />
        Pinned to {pinned}
      </span>
    )
  }

  return (
    <div className="relative">
      <Button size="sm" icon="push_pin" onClick={() => setOpen((v) => !v)}>
        Pin
      </Button>

      {open && (
        <>
          <button
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-40 cursor-default"
          />
          <div className="absolute right-0 z-50 mt-1 w-64 overflow-hidden rounded-lg border border-subtle bg-surface-container-lowest shadow-card">
            <p className="border-b border-subtle px-3 py-2 text-label-md uppercase tracking-wider text-on-surface-variant">
              Pin to
            </p>

            {isPending && (
              <p className="flex items-center gap-2 px-3 py-2 text-body-md text-on-surface-variant">
                <Spinner /> Loading…
              </p>
            )}

            {dashboards?.map((dashboard) => (
              <button
                key={dashboard.id}
                disabled={pin.isPending}
                onClick={() => pin.mutate(dashboard.id)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-body-md text-on-surface-variant transition-colors hover:bg-surface-container-low hover:text-on-surface disabled:opacity-50"
              >
                <span className="truncate">{dashboard.name}</span>
                <span className="shrink-0 font-mono text-[11px] text-outline">
                  {dashboard.tile_count}
                </span>
              </button>
            ))}

            {dashboards?.length === 0 && (
              <p className="px-3 py-2 text-body-md text-outline">
                No dashboards yet.
              </p>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (newName.trim()) create.mutate()
              }}
              className="flex gap-1.5 border-t border-subtle p-2"
            >
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New dashboard…"
                className="text-body-md"
              />
              <Button
                type="submit"
                size="sm"
                variant="primary"
                disabled={!newName.trim()}
                busy={create.isPending}
              >
                Add
              </Button>
            </form>

            {error && (
              <p className="border-t border-subtle px-3 py-2 text-[11px] text-error">
                {error}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
