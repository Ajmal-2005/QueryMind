import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { login, register } from '@/api/auth'
import { errorMessage } from '@/api/client'
import { HealthBadge } from '@/components/HealthBadge'
import { Icon } from '@/components/icons'
import { Alert, Button, Field, IconButton, Input } from '@/components/ui'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

type Mode = 'login' | 'register'

const HIGHLIGHTS = [
  {
    icon: 'chat',
    title: 'Ask in plain English',
    body: 'Questions become validated SQL — no query language required.',
  },
  {
    icon: 'schema',
    title: 'Schema-aware retrieval',
    body: 'Only the tables your question needs reach the model, not all 400.',
  },
  {
    icon: 'shield',
    title: 'Read-only by construction',
    body: 'Four validation gates and a SELECT-only role. Nothing can write.',
  },
]

export function LoginPage() {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const setSession = useAuthStore((s) => s.setSession)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)
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
    <div className="grid h-full lg:grid-cols-2">
      {/* Product panel — hidden on small screens, where the form is all that
          matters. */}
      <section className="relative hidden flex-col justify-between border-r border-subtle bg-surface-container-lowest p-12 lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-on-primary">
            <Icon name="hub" size={20} fill />
          </div>
          <div>
            <p className="text-headline-sm font-bold text-primary">Syntactic Logic</p>
            <p className="text-label-md uppercase tracking-wider text-on-surface-variant">
              NLQ Analytics
            </p>
          </div>
        </div>

        <div className="max-w-md">
          <h2 className="text-[32px] font-bold leading-tight tracking-tight text-primary">
            Your database,
            <br />
            <span className="text-data-indigo">answerable in English.</span>
          </h2>

          <ul className="mt-10 space-y-6">
            {HIGHLIGHTS.map((item) => (
              <li key={item.title} className="flex gap-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-secondary-container text-on-secondary-container">
                  <Icon name={item.icon} size={18} />
                </span>
                <div>
                  <p className="text-body-lg font-semibold text-on-surface">
                    {item.title}
                  </p>
                  <p className="mt-0.5 text-body-md text-on-surface-variant">
                    {item.body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-label-md uppercase tracking-wider text-outline">
          Capstone · Natural Language Query Processing
        </p>
      </section>

      <section className="relative flex flex-col items-center justify-center px-6 py-12">
        <div className="absolute right-5 top-5">
          <IconButton
            icon={theme === 'dark' ? 'light_mode' : 'dark_mode'}
            label="Toggle theme"
            onClick={toggleTheme}
          />
        </div>

        <div className="w-full max-w-sm animate-fade-in">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-on-primary">
              <Icon name="hub" size={20} fill />
            </div>
            <p className="text-headline-sm font-bold text-primary">Syntactic Logic</p>
          </div>

          <h1 className="text-headline-md text-primary">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className="mt-1 text-body-md text-on-surface-variant">
            {mode === 'login'
              ? 'Sign in to your workspace.'
              : 'The first account on this instance becomes the administrator.'}
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            {mode === 'register' && (
              <Field label="NAME">
                <Input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  placeholder="Ada Lovelace"
                />
              </Field>
            )}

            <Field label="EMAIL">
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                placeholder="you@company.com"
              />
            </Field>

            <Field
              label="PASSWORD"
              hint={mode === 'register' ? 'At least 8 characters.' : undefined}
            >
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                placeholder="••••••••••"
              />
            </Field>

            {error && <Alert>{error}</Alert>}

            <Button type="submit" variant="primary" busy={busy} className="w-full">
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>

          <p className="mt-6 text-center text-body-md text-on-surface-variant">
            {mode === 'login' ? "Don't have an account?" : 'Already registered?'}{' '}
            <button
              type="button"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login')
                setError(null)
              }}
              className="font-semibold text-data-indigo underline-offset-4 hover:underline"
            >
              {mode === 'login' ? 'Create one' : 'Sign in'}
            </button>
          </p>

          <div className="mt-10 flex justify-center border-t border-subtle pt-6">
            <HealthBadge />
          </div>
        </div>
      </section>
    </div>
  )
}
