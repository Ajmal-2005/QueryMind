import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { login, register } from '@/api/auth'
import { errorMessage } from '@/api/client'
import { HealthBadge } from '@/components/HealthBadge'
import { useAuthStore } from '@/stores/authStore'

type Mode = 'login' | 'register'

export function LoginPage() {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const setSession = useAuthStore((s) => s.setSession)
  const navigate = useNavigate()
  const location = useLocation()
  const destination = (location.state as { from?: string } | null)?.from ?? '/'

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const session =
        mode === 'login'
          ? await login(email, password)
          : await register(email, password, fullName)
      setSession(session)
      navigate(destination, { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Could not sign you in'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">NLQ Analytics</h1>
        <p className="mt-1 text-sm text-slate-500">
          Ask your database questions in plain English.
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-8 space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
        >
          {mode === 'register' && (
            <Field
              label="Name"
              value={fullName}
              onChange={setFullName}
              type="text"
              autoComplete="name"
            />
          )}

          <Field
            label="Email"
            value={email}
            onChange={setEmail}
            type="email"
            autoComplete="email"
            required
          />

          <Field
            label="Password"
            value={password}
            onChange={setPassword}
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            hint={mode === 'register' ? 'At least 8 characters.' : undefined}
          />

          {error && (
            <p role="alert" className="text-sm text-rose-600">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {busy ? 'Working…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>

          <button
            type="button"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
            className="w-full text-sm text-slate-500 underline-offset-4 hover:underline"
          >
            {mode === 'login'
              ? 'No account yet? Create one'
              : 'Already have an account? Sign in'}
          </button>
        </form>

        <div className="mt-6 flex justify-center">
          <HealthBadge />
        </div>
      </div>
    </div>
  )
}

interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  type: string
  autoComplete?: string
  required?: boolean
  hint?: string
}

function Field({ label, value, onChange, type, autoComplete, required, hint }: FieldProps) {
  const id = `field-${label.toLowerCase()}`
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        required={required}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
      />
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}
