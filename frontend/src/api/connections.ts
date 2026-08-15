import { api } from './client'
import type {
  Connection,
  ConnectionCreate,
  ConnectionTestResult,
  IndexResult,
  SchemaResponse,
} from './types'

export async function listConnections(): Promise<Connection[]> {
  const { data } = await api.get<Connection[]>('/connections')
  return data
}

export async function createConnection(payload: ConnectionCreate): Promise<Connection> {
  const { data } = await api.post<Connection>('/connections', payload)
  return data
}

export async function testConnection(id: string): Promise<ConnectionTestResult> {
  const { data } = await api.post<ConnectionTestResult>(`/connections/${id}/test`)
  return data
}

export async function indexConnection(id: string): Promise<IndexResult> {
  const { data } = await api.post<IndexResult>(`/connections/${id}/index`)
  return data
}

export async function fetchSchema(id: string): Promise<SchemaResponse> {
  const { data } = await api.get<SchemaResponse>(`/connections/${id}/schema`)
  return data
}

export async function deleteConnection(id: string): Promise<void> {
  await api.delete(`/connections/${id}`)
}
