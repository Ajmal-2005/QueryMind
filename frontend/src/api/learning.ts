import { api } from './client'
import type { Correction, GlossaryTerm, Suggestion } from './types'

export async function fetchSuggestions(
  connectionId: string,
  limit = 6,
): Promise<Suggestion[]> {
  const { data } = await api.get<Suggestion[]>('/query/suggestions', {
    params: { connection_id: connectionId, limit },
  })
  return data
}

export async function saveCorrection(payload: {
  connection_id: string
  question: string
  corrected_sql: string
  original_sql?: string | null
  query_id?: string | null
  note?: string | null
}): Promise<Correction> {
  const { data } = await api.post<Correction>('/learning/corrections', payload)
  return data
}

export async function listCorrections(
  connectionId: string,
): Promise<Correction[]> {
  const { data } = await api.get<Correction[]>('/learning/corrections', {
    params: { connection_id: connectionId },
  })
  return data
}

export async function deleteCorrection(id: string): Promise<void> {
  await api.delete(`/learning/corrections/${id}`)
}

export async function listGlossary(
  connectionId: string,
): Promise<GlossaryTerm[]> {
  const { data } = await api.get<GlossaryTerm[]>('/learning/glossary', {
    params: { connection_id: connectionId },
  })
  return data
}

export async function saveTerm(payload: {
  connection_id: string
  term: string
  definition: string
  sql_expression?: string | null
}): Promise<GlossaryTerm> {
  const { data } = await api.post<GlossaryTerm>('/learning/glossary', payload)
  return data
}

export async function deleteTerm(id: string): Promise<void> {
  await api.delete(`/learning/glossary/${id}`)
}
