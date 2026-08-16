/** Account, appearance, usage and system status.
 *
 *  This page exists partly to give the infrastructure detail somewhere honest
 *  to live. It used to sit in the app header — "database healthy · redis off"
 *  — where it asked every user to interpret services they did not configure.
 *  Here it is available to someone who went looking for it, which is the
 *  difference between diagnostics and noise.
 */

import { useQuery } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { fetchHealth } from '@/api/health'
import { fetchCacheStatus, fetchUsage } from '@/api/usage'
import type { ServiceStatus } from '@/api/types'
import { Icon } from '@/components/icons'
import { Alert, Pill, Skeleton } from '@/components/ui'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

const SERVICE_TONE: Record<ServiceStatus, 'online' | 'amber' | 'offline' | 'neutral'> =
  {
    ok: 'online',
    degraded: 'amber',
    unavailable: 'offline',
    not_configured: 'neutral',
  }

const SERVICE_LABEL: Record<ServiceStatus, string> = {
  ok: 'Responding',
  degraded: 'Degraded',
  unavailable: 'Unreachable',
  // Not a fault: an unset Redis is a deployment choice, and the app runs an
  // in-process cache instead.
  not_configured: 'Not configured',
}

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-subtle bg-surface-container-lowest p-5 shadow-card">
      <h3 className="text-headline-sm text-primary">{title}</h3>
      {description && (
        <p className="mt-1 text-body-md text-on-surface-variant">{description}</p>
      )}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle py-2.5 last:border-0">
      <span className="text-body-md text-on-surface-variant">{label}</span>
      <span className="text-body-md text-on-surface">{children}</span>
    </div>
  )
}

export function SettingsPage() {
  const user = useAuthStore((s) => s.user)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)

  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth })
  const usage = useQuery({ queryKey: ['usage'], queryFn: () => fetchUsage(30) })
  const cache = useQuery({ queryKey: ['cache'], queryFn: fetchCacheStatus })

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-2 text-headline-lg-mobile text-primary md:text-headline-lg">
          Settings
        </h2>
        <p className="max-w-2xl text-body-lg text-on-surface-variant">
          Your account, what you have spent, and what the system is doing.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Account">
          <Row label="Email">{user?.email ?? '—'}</Row>
          <Row label="Role">
            <span className="capitalize">{user?.role ?? '—'}</span>
          </Row>
          <Row label="Member since">
            {user?.created_at
              ? new Date(user.created_at).toLocaleDateString()
              : '—'}
          </Row>
        </Section>

        <Section title="Appearance">
          <Row label="Theme">
            <button
              onClick={toggleTheme}
              className="flex items-center gap-1.5 rounded-md border border-subtle px-2.5 py-1 text-label-md text-on-surface-variant transition-colors hover:border-primary hover:text-primary"
            >
              <Icon name={theme === 'dark' ? 'dark_mode' : 'light_mode'} size={15} />
              {theme === 'dark' ? 'Dark' : 'Light'}
            </button>
          </Row>
        </Section>

        <Section
          title="Usage"
          description="Last 30 days. Costs are estimates, not an invoice."
        >
          {usage.isPending ? (
            <Skeleton className="h-32" />
          ) : usage.error ? (
            <Alert>{errorMessage(usage.error, 'Could not load usage')}</Alert>
          ) : usage.data ? (
            <>
              <Row label="Questions asked">
                {usage.data.totals.queries.toLocaleString()}
              </Row>
              <Row label="Answered">
                {usage.data.totals.executed.toLocaleString()}
              </Row>
              <Row label="Blocked by a safety gate">
                {usage.data.totals.rejected.toLocaleString()}
              </Row>
              <Row label="Repaired by self-correction">
                {usage.data.totals.recovered_by_correction.toLocaleString()}
              </Row>
              <Row label="Tokens">{usage.data.totals.tokens.toLocaleString()}</Row>
              <Row label="Estimated cost">
                ${usage.data.totals.estimated_cost_usd.toFixed(4)}
              </Row>
              <Row label="Mean latency">
                {Math.round(usage.data.totals.mean_latency_ms)} ms
              </Row>
              <p className="mt-3 text-[11px] text-outline">
                Showing {usage.data.scope === 'you' ? 'your own' : 'all users’'}{' '}
                activity. {usage.data.cost_note}
              </p>
            </>
          ) : null}
        </Section>

        <Section
          title="System"
          description="Infrastructure this deployment is running against."
        >
          {health.isPending ? (
            <Skeleton className="h-32" />
          ) : health.error ? (
            <Alert>The API is not responding.</Alert>
          ) : health.data ? (
            <>
              <Row label="Version">
                <span className="font-mono text-[12px]">
                  {health.data.version}
                </span>
              </Row>
              <Row label="Environment">
                <span className="capitalize">{health.data.environment}</span>
              </Row>
              {Object.entries(health.data.services).map(([name, service]) => (
                <Row key={name} label={name[0].toUpperCase() + name.slice(1)}>
                  <span title={service.detail ?? undefined}>
                    <Pill tone={SERVICE_TONE[service.status]}>
                      {SERVICE_LABEL[service.status]}
                      {service.latency_ms !== null &&
                        ` · ${Math.round(service.latency_ms)} ms`}
                    </Pill>
                  </span>
                </Row>
              ))}
              {cache.data && (
                <Row label="Result cache">
                  <span
                    title={`${cache.data.hits} hits, ${cache.data.misses} misses`}
                  >
                    {cache.data.backend} · {(cache.data.hit_rate * 100).toFixed(0)}%
                    hit rate · {cache.data.ttl_seconds}s TTL
                  </span>
                </Row>
              )}
            </>
          ) : null}
        </Section>
      </div>
    </div>
  )
}
