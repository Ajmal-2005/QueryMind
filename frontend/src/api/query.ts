import { api } from './client'
import type { QueryResponse } from './types'

export async function askQuestion(payload: {
  connection_id: string
  question: string
  session_id?: string
}): Promise<QueryResponse> {
  const { data } = await api.post<QueryResponse>('/query', payload)
  return data
}
