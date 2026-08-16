import { api } from './client'
import type { CacheStatus, UsageResponse } from './types'

export async function fetchUsage(days = 30): Promise<UsageResponse> {
  const { data } = await api.get<UsageResponse>('/usage', { params: { days } })
  return data
}

export async function fetchCacheStatus(): Promise<CacheStatus> {
  const { data } = await api.get<CacheStatus>('/query/cache')
  return data
}
