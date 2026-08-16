/** Narrative insight (F13).
 *
 *  Fetched after the table and chart are already on screen, because it is the
 *  one analytics step that costs an LLM round trip. The result is useful
 *  without it; making the user wait for prose before seeing their own data
 *  would be the wrong trade.
 */

import { useQuery } from '@tanstack/react-query'

import { fetchInsight } from '@/api/analytics'
import { errorMessage } from '@/api/client'
import { Icon } from '@/components/icons'
import { Spinner } from '@/components/ui'

export function InsightPanel({
  connectionId,
  sql,
  question,
}: {
  connectionId: string
  sql: string
  question: string
}) {
  const { data, isPending, error } = useQuery({
    queryKey: ['insight', connectionId, sql],
    queryFn: () => fetchInsight({ connection_id: connectionId, sql, question }),
    // The same SQL over the same connection yields the same summary, and the
    // backend caches the rows anyway — no reason to pay for it twice.
    staleTime: 5 * 60_000,
    retry: false,
  })

  if (isPending) {
    return (
      <p className="flex items-center gap-2 text-body-md text-on-surface-variant">
        <Spinner /> Writing a summary…
      </p>
    )
  }

  if (error) {
    return (
      <p className="flex items-center gap-1.5 text-body-md text-outline">
        <Icon name="info" size={14} />
        No summary available: {errorMessage(error, 'the narrator failed')}
      </p>
    )
  }

  return (
    <div className="rounded-md border border-subtle bg-surface-bg p-4">
      <p className="mb-1.5 flex items-center gap-1.5 text-label-md uppercase tracking-wider text-on-surface-variant">
        <Icon name="lightbulb" size={14} />
        Insight
      </p>

      <p className="text-body-lg text-on-surface">{data.headline}</p>
      <p className="mt-1 text-body-md text-on-surface-variant">{data.summary}</p>

      {data.findings.length > 0 && (
        <ul className="mt-2 space-y-1 text-body-md text-on-surface-variant">
          {data.findings.map((finding) => (
            <li key={finding} className="flex gap-2">
              <span className="text-outline">•</span>
              {finding}
            </li>
          ))}
        </ul>
      )}

      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-subtle pt-2 text-[11px] text-outline">
        <span>
          written by <span className="font-mono text-on-surface-variant">{data.model}</span>
        </span>
        {data.model === 'template' && (
          <span className="text-data-amber">
            computed from the statistics — no language model was called
          </span>
        )}
        {data.masked_columns.length > 0 && (
          <span
            title={data.masked_columns
              .map((c) => `${c.column} — ${c.detected_as}, by ${c.rule}`)
              .join('\n')}
            className="flex items-center gap-1 text-sql-syntax-string"
          >
            <Icon name="shield" size={12} />
            {data.masked_columns.length} column
            {data.masked_columns.length === 1 ? '' : 's'} masked before sending
          </span>
        )}
      </dl>
    </div>
  )
}
