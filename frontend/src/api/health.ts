import { api } from './client'
import type { HealthResponse } from './types'

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health')
  return data
}
