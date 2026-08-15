import { useNavigate } from 'react-router-dom'

import { HealthBadge } from '@/components/HealthBadge'
import { useAuthStore } from '@/stores/authStore'

/** Phase 0 placeholder. The chat surface lands in phase 2. */
export function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const navigate = useNavigate()

  function signOut() {
    clear()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">NLQ Analytics</h1>
          <p className="mt-1 text-sm text-slate-500">
            Signed in as {user?.email} · {user?.role}
          </p>
        </div>
        <button
          onClick={signOut}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
        >
          Sign out
        </button>
      </header>

      <section className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          System status
        </h2>
        <div className="mt-3">
          <HealthBadge />
        </div>
      </section>

      <section className="mt-6 rounded-xl border border-dashed border-slate-300 p-6">
        <h2 className="font-medium text-slate-700">Next up</h2>
        <ol className="mt-3 space-y-2 text-sm text-slate-600">
          <li>
            <span className="font-medium">Phase 1</span> — connection manager and
            schema introspection
          </li>
          <li>
            <span className="font-medium">Phase 2</span> — the NL→SQL core: intent,
            retrieval, generation
          </li>
          <li>
            <span className="font-medium">Phase 3</span> — validation gates and
            sandboxed execution
          </li>
        </ol>
      </section>
    </div>
  )
}
