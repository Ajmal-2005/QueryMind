import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/api/health'
import type { ServiceStatus } from '@/api/types'

const DOT: Record<ServiceStatus, string> = {
  ok: 'bg-emerald-500',
  degraded: 'bg-amber-500',
  unavailable: 'bg-rose-500',
  not_configured: 'bg-slate-300',
}

const LABEL: Record<ServiceStatus, string> = {
  ok: 'healthy',
  degraded: 'degraded',
  unavailable: 'unreachable',
  not_configured: 'not configured',
}

export function HealthBadge() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: 1,
  })

  if (isPending) {
    return <span className="text-sm text-slate-400">Checking services…</span>
  }

  if (isError || !data) {
    return (
      <span className="flex items-center gap-2 text-sm text-rose-600">
        <span className="h-2 w-2 rounded-full bg-rose-500" />
        Backend unreachable
      </span>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className="font-medium text-slate-700">
        API v{data.version} · {data.environment}
      </span>
      {Object.entries(data.services).map(([name, service]) => (
        <span key={name} className="flex items-center gap-1.5 text-slate-500">
          <span className={`h-2 w-2 rounded-full ${DOT[service.status]}`} />
          {name} {LABEL[service.status]}
        </span>
      ))}
    </div>
  )
}
