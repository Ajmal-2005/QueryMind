import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/api/health'
import type { ServiceStatus } from '@/api/types'
import { Skeleton } from '@/components/ui'

const DOT: Record<ServiceStatus, string> = {
  ok: 'bg-sql-syntax-string',
  degraded: 'bg-data-amber',
  unavailable: 'bg-error',
  not_configured: 'bg-outline',
}

const LABEL: Record<ServiceStatus, string> = {
  ok: 'healthy',
  degraded: 'degraded',
  unavailable: 'unreachable',
  not_configured: 'off',
}

export function HealthBadge() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: 1,
  })

  if (isPending) return <Skeleton className="h-5 w-48" />

  if (isError || !data) {
    return (
      <span className="flex items-center gap-1.5 text-label-md text-error">
        <span className="h-1.5 w-1.5 rounded-full bg-error" />
        Backend unreachable
      </span>
    )
  }

  return (
    <div className="flex items-center gap-3">
      <span className="font-mono text-[11px] text-outline">
        v{data.version} · {data.environment}
      </span>
      {Object.entries(data.services).map(([name, service]) => (
        <span
          key={name}
          className="flex items-center gap-1.5 text-label-md text-on-surface-variant"
          title={service.detail ?? undefined}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${DOT[service.status]}`} />
          {name}
          <span className="font-normal normal-case tracking-normal text-outline">
            {LABEL[service.status]}
          </span>
        </span>
      ))}
    </div>
  )
}
