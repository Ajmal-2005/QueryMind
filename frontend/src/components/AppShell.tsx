import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { HealthBadge } from '@/components/HealthBadge'
import { Icon } from '@/components/icons'
import { IconButton } from '@/components/ui'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

interface NavEntry {
  icon: string
  label: string
  to: string
}

const NAV: NavEntry[] = [
  { icon: 'terminal', label: 'Ask', to: '/ask' },
  { icon: 'cloud_sync', label: 'Connections', to: '/connections' },
  { icon: 'menu_book', label: 'Glossary', to: '/glossary' },
  { icon: 'dashboard', label: 'Dashboards', to: '/dashboards' },
  { icon: 'settings', label: 'Settings', to: '/settings' },
]

export function AppShell({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)
  const navigate = useNavigate()

  function signOut() {
    clear()
    navigate('/login', { replace: true })
  }

  const initials =
    (user?.full_name || user?.email || '?')
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || '?'

  return (
    <div className="flex h-screen overflow-hidden">
      <nav className="fixed left-0 top-0 z-40 hidden h-full w-sidebar flex-col border-r border-subtle bg-surface-container-lowest p-4 md:flex">
        <div className="mb-8 flex items-center gap-3 px-2">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-on-primary">
            <Icon name="hub" size={20} fill />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-headline-sm font-bold text-primary">
              Syntactic Logic
            </h1>
            <p className="text-label-md uppercase tracking-wider text-on-surface-variant">
              NLQ Analytics
            </p>
          </div>
        </div>

        <button
          onClick={() => navigate('/ask')}
          className="mb-6 flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-2.5 text-label-md text-on-primary transition-opacity hover:bg-opacity-90"
        >
          <Icon name="add" size={18} />
          New Query
        </button>

        <div className="flex flex-1 flex-col gap-1">
          {NAV.map((entry) => (
            <NavItem key={entry.label} entry={entry} />
          ))}
        </div>

        <div className="mt-auto border-t border-subtle pt-4">
          <div className="flex items-center gap-3 rounded-lg px-3 py-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-fixed text-label-md text-on-primary-container">
              {initials}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-body-md text-on-surface">{user?.email}</p>
              <p className="text-label-md capitalize text-on-surface-variant">
                {user?.role}
              </p>
            </div>
          </div>
        </div>
      </nav>

      <div className="relative flex h-full min-w-0 flex-1 flex-col md:ml-sidebar">
        <header className="sticky top-0 z-30 flex h-16 w-full shrink-0 items-center justify-between gap-4 border-b border-subtle bg-surface px-margin-mobile md:px-margin-desktop">
          <div className="flex min-w-0 flex-1 items-center gap-4">
            <span className="text-headline-sm font-bold text-primary md:hidden">
              Syntactic Logic
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <div className="hidden lg:block">
              <HealthBadge />
            </div>
            <span className="mx-1 hidden h-6 w-px bg-subtle lg:block" />
            <IconButton
              icon={theme === 'dark' ? 'light_mode' : 'dark_mode'}
              label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              onClick={toggleTheme}
            />
            <IconButton icon="logout" label="Sign out" onClick={signOut} />
            {/* Was a bare <span>: it looked like a control and did nothing.
                An avatar in this position is expected to open the account,
                so it does. */}
            <NavLink
              to="/settings"
              title="Account settings"
              className="ml-1 flex h-8 w-8 items-center justify-center rounded-full border border-subtle bg-primary-fixed text-label-md text-on-primary-container transition-colors hover:border-primary"
            >
              {initials}
            </NavLink>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-gutter md:p-margin-desktop">
          <div className="mx-auto flex h-full w-full max-w-container-max flex-col">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}

function NavItem({ entry }: { entry: NavEntry }) {
  return (
    <NavLink
      to={entry.to}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2.5 text-label-md transition-colors ${
          isActive
            ? 'scale-[0.98] bg-secondary-container text-on-secondary-container'
            : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon name={entry.icon} size={20} fill={isActive} />
          <span className="flex-1">{entry.label}</span>
        </>
      )}
    </NavLink>
  )
}
