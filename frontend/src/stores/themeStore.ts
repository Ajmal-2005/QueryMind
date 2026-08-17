import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'nlq.theme'
const SUPPRESS_CLASS = 'theme-switching'

function initialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  // No stored preference: follow the operating system.
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function apply(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

/** Flip the theme with every CSS transition suppressed.
 *
 *  Colours come from custom properties. An element that transitions a
 *  property fed by a variable can keep its pre-change computed value when
 *  that variable is swapped - the card backgrounds stayed dark in light mode
 *  because of exactly this. Killing transitions for the duration of the swap
 *  avoids the stale paint, and makes the change instant rather than a
 *  half-second cross-fade.
 */
function applyWithoutTransitions(theme: Theme) {
  const root = document.documentElement
  root.classList.add(SUPPRESS_CLASS)
  apply(theme)
  // Force a synchronous style recalculation so the new colours are committed
  // before transitions are allowed again.
  void root.offsetHeight
  requestAnimationFrame(() => root.classList.remove(SUPPRESS_CLASS))
}

interface ThemeState {
  theme: Theme
  toggle: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  toggle: () => {
    const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem(STORAGE_KEY, next)
    applyWithoutTransitions(next)
    set({ theme: next })
  },
}))

// Paint before first render so there is no flash of the wrong theme.
apply(useThemeStore.getState().theme)
