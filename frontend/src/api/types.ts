export type UserRole = 'admin' | 'analyst' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export type ServiceStatus = 'ok' | 'degraded' | 'unavailable' | 'not_configured'

export interface ServiceHealth {
  status: ServiceStatus
  detail: string | null
  latency_ms: number | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  environment: string
  services: Record<string, ServiceHealth>
}
