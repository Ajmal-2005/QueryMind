import axios, { AxiosError } from 'axios'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

/** Read the token straight from storage so this module stays free of store imports. */
export const TOKEN_KEY = 'nlq.access_token'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // An expired or revoked token should drop the session rather than leave
    // the UI in a half-authenticated state.
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      window.dispatchEvent(new Event('nlq:unauthorized'))
    }
    return Promise.reject(error)
  },
)

/** Pull the human-readable message out of a FastAPI error response. */
export function errorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
    if (!error.response) return 'Cannot reach the server. Is the backend running?'
  }
  return fallback
}
