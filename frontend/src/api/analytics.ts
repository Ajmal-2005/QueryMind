import { api } from './client'
import type { Analysis, ExportFormat, Narrative } from './types'

export interface ResultRef {
  connection_id: string
  sql: string
  question?: string
}

export async function fetchInsight(payload: ResultRef): Promise<Narrative> {
  const { data } = await api.post<Narrative>('/query/insight', payload)
  return data
}

export async function analyzeSql(payload: ResultRef): Promise<Analysis> {
  const { data } = await api.post<Analysis>('/query/analyze', payload)
  return data
}

/** Ask the server for a file and hand it to the browser to save.
 *
 *  The blob comes back from an authenticated POST, so a plain `<a href>` to
 *  the endpoint would not carry the bearer token. An object URL sidesteps
 *  that without putting the SQL in a query string.
 */
export async function downloadExport(
  payload: ResultRef & {
    format: ExportFormat
    title?: string
    include_narrative?: boolean
    chart_png?: string | null
  },
): Promise<void> {
  const response = await api.post('/query/export', payload, {
    responseType: 'blob',
  })

  const disposition = String(response.headers['content-disposition'] ?? '')
  const name =
    /filename="([^"]+)"/.exec(disposition)?.[1] ??
    `query-result.${payload.format}`

  const url = URL.createObjectURL(response.data as Blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
