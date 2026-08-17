/** One answered question, fully rendered: chart, table, statistics, summary.
 *
 *  The Phase 4 deliverable in one component - every query comes back with a
 *  table, an appropriate chart, and a written summary. Shared by the Ask page
 *  and reused for dashboard tiles, so the two cannot drift apart.
 */

import { useRef, useState } from 'react'

import type { Analysis, ChartSpec, ResultSet } from '@/api/types'
import { ChartControls } from '@/components/ChartControls'
import { ChartView } from '@/components/ChartView'
import { ExportMenu } from '@/components/ExportMenu'
import { Icon } from '@/components/icons'
import { InsightPanel } from '@/components/InsightPanel'
import { PinToDashboard } from '@/components/PinToDashboard'
import { ProfilePanel } from '@/components/ProfilePanel'
import { ResultTable } from '@/components/ResultTable'

export function ResultView({
  result,
  analysis,
  connectionId,
  sql,
  question,
  queryId,
}: {
  result: ResultSet
  analysis: Analysis
  connectionId: string
  sql: string
  question: string
  queryId?: string | null
}) {
  const [spec, setSpec] = useState<ChartSpec>(analysis.chart)
  const [showTable, setShowTable] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)

  const drawn = spec.type !== 'table'
  const title = question.slice(0, 60) || 'Query result'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {drawn && (
          <button
            onClick={() => setShowTable((v) => !v)}
            className="flex items-center gap-1 text-label-md text-on-surface-variant transition-colors hover:text-primary"
          >
            <Icon name={showTable ? 'visibility_off' : 'table_rows'} size={15} />
            {showTable ? 'Hide table' : 'Show table'}
          </button>
        )}
        <PinToDashboard
          connectionId={connectionId}
          sql={sql}
          question={question}
          queryId={queryId}
          chart={spec}
        />
        <ExportMenu
          connectionId={connectionId}
          sql={sql}
          question={question}
          title={title}
          chartRef={chartRef}
          hasChart={drawn && spec.type !== 'kpi'}
        />
      </div>

      <div ref={chartRef}>
        <ChartView result={result} spec={spec} analysis={analysis} />
      </div>

      {(drawn || showTable) && (
        <ChartControls
          analysis={analysis}
          spec={spec}
          onChange={setSpec}
          onReset={() => setSpec(analysis.chart)}
        />
      )}

      {drawn && showTable && <ResultTable result={result} />}

      {result.cached && (
        <p className="flex items-center gap-1.5 text-[11px] text-outline">
          <Icon name="bolt" size={12} />
          Served from the result cache - this query did not re-run against the
          database, so the timing above is the cache lookup.
        </p>
      )}

      <InsightPanel connectionId={connectionId} sql={sql} question={question} />
      <ProfilePanel analysis={analysis} />
    </div>
  )
}
