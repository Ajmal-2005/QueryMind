import { create } from 'zustand'

import { TOKEN_KEY } from '@/api/client'
import type { TokenResponse, User } from '@/api/types'

const USER_KEY = 'nlq.user'

interface AuthState {
  token: string | null
  user: User | null
  setSession: (payload: TokenResponse) => void
  setUser: (user: User) => void
  clear: () => void
  isAuthenticated: () => boolean
}

function readStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as User
  } catch {
    // Corrupted entry - drop it rather than crash the app on boot.
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: readStoredUser(),

  setSession: ({ access_token, user }) => {
    localStorage.setItem(TOKEN_KEY, access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
    set({ token: access_token, user })
  },

  setUser: (user) => {
    localStorage.setItem(USER_KEY, JSON.stringify(user))
    set({ user })
  },

  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    set({ token: null, user: null })
  },

  isAuthenticated: () => Boolean(get().token),
}))

// The API client fires this when any request comes back 401.
window.addEventListener('nlq:unauthorized', () => {
  useAuthStore.getState().clear()
})
