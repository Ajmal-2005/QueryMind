/** One-glance system status for the app header.
 *
 *  Deliberately says one thing. An earlier version listed every service and
 *  its state — "database healthy · redis off" — which is telemetry, not
 *  product: it asks the user to interpret infrastructure they did not
 *  configure and cannot act on. The detail still exists, on the Settings
 *  page, where someone looking for it will go.
 */

import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/api/health'
import { Skeleton } from '@/components/ui'

export function HealthBadge() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: 1,
  })

  if (isPending) return <Skeleton className="h-5 w-24" />

  if (isError || !data) {
    return (
      <span
        className="flex items-center gap-1.5 text-label-md text-error"
        title="The API is not responding."
      >
        <span className="h-1.5 w-1.5 rounded-full bg-error" />
        Offline
      </span>
    )
  }

  const healthy = data.status === 'ok'
  // Only services that are actually configured can be degraded — an unset
  // Redis is a deployment choice, not a fault, and must not show as one.
  const troubled = Object.entries(data.services)
    .filter(([, s]) => s.status === 'degraded' || s.status === 'unavailable')
    .map(([name]) => name)

  return (
    <span
      className={`flex items-center gap-1.5 text-label-md ${
        healthy ? 'text-on-surface-variant' : 'text-data-amber'
      }`}
      title={
        troubled.length
          ? `Degraded: ${troubled.join(', ')}. See Settings for detail.`
          : 'All services responding.'
      }
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          healthy ? 'bg-sql-syntax-string' : 'bg-data-amber'
        }`}
      />
      {healthy ? 'Connected' : 'Degraded'}
    </span>
  )
}
