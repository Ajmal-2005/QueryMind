import { api } from './client'
import type {
  Dashboard,
  DashboardDetail,
  DashboardRefresh,
  DashboardTile,
} from './types'

export async function listDashboards(): Promise<Dashboard[]> {
  const { data } = await api.get<Dashboard[]>('/dashboards')
  return data
}

export async function getDashboard(id: string): Promise<DashboardDetail> {
  const { data } = await api.get<DashboardDetail>(`/dashboards/${id}`)
  return data
}

export async function createDashboard(payload: {
  name: string
  description?: string
}): Promise<Dashboard> {
  const { data } = await api.post<Dashboard>('/dashboards', payload)
  return data
}

export async function deleteDashboard(id: string): Promise<void> {
  await api.delete(`/dashboards/${id}`)
}

export async function addTile(
  dashboardId: string,
  payload: {
    title: string
    connection_id: string
    sql: string
    question?: string | null
    query_id?: string | null
    chart?: Record<string, unknown>
  },
): Promise<DashboardTile> {
  const { data } = await api.post<DashboardTile>(
    `/dashboards/${dashboardId}/tiles`,
    payload,
  )
  return data
}

export async function deleteTile(
  dashboardId: string,
  tileId: string,
): Promise<void> {
  await api.delete(`/dashboards/${dashboardId}/tiles/${tileId}`)
}

/** Re-run every tile. Nothing is precomputed — a dashboard showing last
 *  Tuesday's figures is worse than no dashboard. */
export async function refreshDashboard(id: string): Promise<DashboardRefresh> {
  const { data } = await api.post<DashboardRefresh>(`/dashboards/${id}/refresh`)
  return data
}
