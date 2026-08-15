import { useNavigate } from 'react-router-dom'

import { HealthBadge } from '@/components/HealthBadge'
import { ConnectionsPage } from '@/pages/ConnectionsPage'
import { useAuthStore } from '@/stores/authStore'

export function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const navigate = useNavigate()

  function signOut() {
    clear()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">NLQ Analytics</h1>
          <p className="mt-1 text-sm text-slate-500">
            Signed in as {user?.email} · {user?.role}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <HealthBadge />
          <button
            onClick={signOut}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="mt-8">
        <ConnectionsPage />
      </main>

      <section className="mt-8 rounded-xl border border-dashed border-slate-300 p-5">
        <h2 className="text-sm font-medium text-slate-700">Coming next</h2>
        <p className="mt-2 text-sm text-slate-600">
          <span className="font-medium">Phase 2</span> — ask a question in plain
          English: intent analysis, schema-linked retrieval over the index above, and
          SQL generation.
        </p>
      </section>
    </div>
  )
}
