/** Manual chart override (F12).
 *
 *  The backend's recommendation is a starting point, not a verdict. This lets
 *  the user pick a different type and different axes, and offers only the
 *  columns whose inferred kind makes sense for each slot - the axis lists come
 *  from the same profile that produced the recommendation, so the two cannot
 *  disagree about what counts as a category.
 */

import type { Analysis, ChartSpec, ChartType } from '@/api/types'
import { Icon } from '@/components/icons'

const TYPE_LABEL: Record<ChartType, string> = {
  line: 'Line',
  bar: 'Bar',
  pie: 'Pie',
  scatter: 'Scatter',
  kpi: 'KPI',
  table: 'Table',
}

const TYPE_ICON: Record<ChartType, string> = {
  line: 'show_chart',
  bar: 'bar_chart',
  pie: 'pie_chart',
  scatter: 'scatter_plot',
  kpi: 'numbers',
  table: 'table_rows',
}

/** X-axis candidates for a given chart type. */
function xOptions(analysis: Analysis, type: ChartType): string[] {
  const { temporal = [], categorical = [], numeric = [] } = analysis.options
  if (type === 'scatter') return numeric
  if (type === 'line') return [...temporal, ...categorical]
  return [...categorical, ...temporal]
}

export function ChartControls({
  analysis,
  spec,
  onChange,
  onReset,
}: {
  analysis: Analysis
  spec: ChartSpec
  onChange: (next: ChartSpec) => void
  onReset: () => void
}) {
  const numeric = analysis.options.numeric ?? []
  const overridden =
    spec.type !== analysis.chart.type ||
    spec.x !== analysis.chart.x ||
    spec.y.join() !== analysis.chart.y.join()

  // Offer every type the backend endorsed, plus whichever it chose.
  const types = [
    ...new Set<ChartType>([analysis.chart.type, ...analysis.chart.alternatives]),
  ]

  function pickType(type: ChartType) {
    const xs = xOptions(analysis, type)
    onChange({
      ...spec,
      type,
      x: xs.includes(spec.x ?? '') ? spec.x : (xs[0] ?? null),
      // Scatter plots one measure against another, so the recommendation's
      // multi-series y list has to collapse to a single column.
      y: type === 'scatter' ? spec.y.slice(0, 1) : spec.y,
    })
  }

  const xs = xOptions(analysis, spec.type)

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-subtle pt-3">
      <div className="flex items-center gap-1" role="group" aria-label="Chart type">
        {types.map((type) => (
          <button
            key={type}
            onClick={() => pickType(type)}
            aria-pressed={spec.type === type}
            title={TYPE_LABEL[type]}
            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-label-md transition-colors ${
              spec.type === type
                ? 'border-primary bg-secondary-container text-on-secondary-container'
                : 'border-subtle text-on-surface-variant hover:text-on-surface'
            }`}
          >
            <Icon name={TYPE_ICON[type]} size={15} />
            {TYPE_LABEL[type]}
          </button>
        ))}
      </div>

      {spec.type !== 'table' && spec.type !== 'kpi' && (
        <>
          {xs.length > 1 && (
            <label className="flex items-center gap-1.5 text-label-md text-on-surface-variant">
              X
              <select
                value={spec.x ?? ''}
                onChange={(e) => onChange({ ...spec, x: e.target.value })}
                className="rounded border border-outline-variant bg-surface-container-lowest px-1.5 py-0.5 text-body-md text-on-surface focus:border-data-indigo focus:outline-none"
              >
                {xs.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {numeric.length > 1 && (
            <label className="flex items-center gap-1.5 text-label-md text-on-surface-variant">
              Y
              <select
                value={spec.y[0] ?? ''}
                onChange={(e) => onChange({ ...spec, y: [e.target.value] })}
                className="rounded border border-outline-variant bg-surface-container-lowest px-1.5 py-0.5 text-body-md text-on-surface focus:border-data-indigo focus:outline-none"
              >
                {numeric.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      )}

      {overridden ? (
        <button
          onClick={onReset}
          className="flex items-center gap-1 text-label-md text-on-surface-variant transition-colors hover:text-primary"
        >
          <Icon name="restart_alt" size={14} />
          Reset
        </button>
      ) : (
        <span
          title={analysis.chart.reason}
          className="flex items-center gap-1 text-[11px] text-outline"
        >
          <Icon name="auto_awesome" size={12} />
          chosen automatically
        </span>
      )}
    </div>
  )
}
