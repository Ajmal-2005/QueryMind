/** Renders a result set as the chart a `ChartSpec` asks for (F11).
 *
 *  The spec is the backend's, derived from the profile; this file only draws
 *  it. Keeping selection on the server means the dashboard refresh, the PDF
 *  export and this component all agree about what a result should look like.
 */

import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'

import type { Analysis, ChartSpec, ResultSet } from '@/api/types'
import { ResultTable } from '@/components/ResultTable'

/** Categorical palette. Distinguishable in both themes and, in this order,
 *  distinguishable under the common forms of colour blindness. */
const SERIES_COLORS = [
  '#6366f1',
  '#f59e0b',
  '#10b981',
  '#ec4899',
  '#06b6d4',
  '#8b5cf6',
  '#ef4444',
  '#84cc16',
]

const AXIS = {
  stroke: 'currentColor',
  fontSize: 11,
  tickLine: false,
}

function compact(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (magnitude >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(2)
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-subtle bg-surface-container-lowest px-3 py-2 shadow-card">
      {label !== undefined && (
        <p className="mb-1 text-label-md text-on-surface">{String(label)}</p>
      )}
      {payload.map((entry: any) => (
        <p key={entry.name} className="flex items-center gap-1.5 text-body-md">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: entry.color ?? entry.fill }}
          />
          <span className="text-on-surface-variant">{entry.name}</span>
          <span className="ml-2 font-mono tabular-nums text-on-surface">
            {typeof entry.value === 'number'
              ? entry.value.toLocaleString()
              : String(entry.value)}
          </span>
        </p>
      ))}
    </div>
  )
}

/** Rows as objects keyed by column name - what Recharts consumes. */
function useChartData(result: ResultSet, spec: ChartSpec) {
  return useMemo(() => {
    const index = new Map(result.columns.map((name, i) => [name, i]))

    const raw = result.rows.map((row) => {
      const record: Record<string, unknown> = {}
      for (const [name, i] of index) record[name] = row[i]
      return record
    })

    // A series column turns long-format rows into one key per series value,
    // which is the shape Recharts needs for multiple lines on one axis.
    if (!spec.series || !spec.x || spec.y.length !== 1) return raw

    const measure = spec.y[0]
    const byPeriod = new Map<string, Record<string, unknown>>()
    for (const record of raw) {
      const period = String(record[spec.x])
      const bucket = byPeriod.get(period) ?? { [spec.x]: record[spec.x] }
      bucket[String(record[spec.series])] = record[measure]
      byPeriod.set(period, bucket)
    }
    return [...byPeriod.values()]
  }, [result, spec])
}

function seriesKeys(
  data: Record<string, unknown>[],
  spec: ChartSpec,
): string[] {
  if (!spec.series) return spec.y
  const keys = new Set<string>()
  for (const record of data) {
    for (const key of Object.keys(record)) if (key !== spec.x) keys.add(key)
  }
  return [...keys]
}

export function ChartView({
  result,
  spec,
  analysis,
  height = 280,
}: {
  result: ResultSet
  spec: ChartSpec
  analysis?: Analysis
  height?: number
}) {
  const data = useChartData(result, spec)
  const keys = seriesKeys(data, spec)

  if (spec.type === 'table') return <ResultTable result={result} />

  if (spec.type === 'kpi') {
    const column = spec.y[0]
    const value = data[0]?.[column]
    const label = spec.x ? String(data[0]?.[spec.x] ?? '') : ''

    return (
      <div className="rounded-md border border-subtle bg-surface-bg px-6 py-8 text-center">
        <p className="font-mono text-[2.75rem] leading-none tabular-nums text-primary">
          {typeof value === 'number' ? value.toLocaleString() : String(value ?? '-')}
        </p>
        <p className="mt-2 text-label-md uppercase tracking-wider text-on-surface-variant">
          {label || column}
        </p>
      </div>
    )
  }

  // `text-outline` supplies `currentColor` to the axes and grid, so both
  // themes get readable chrome without a colour lookup here.
  return (
    <div className="text-outline" style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        {spec.type === 'line' ? (
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} />
            <XAxis dataKey={spec.x ?? undefined} {...AXIS} />
            <YAxis tickFormatter={compact} {...AXIS} width={52} />
            <Tooltip content={<ChartTooltip />} />
            {keys.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {keys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={data.length <= 40}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        ) : spec.type === 'bar' ? (
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} vertical={false} />
            <XAxis
              dataKey={spec.x ?? undefined}
              {...AXIS}
              interval={0}
              angle={data.length > 6 ? -35 : 0}
              textAnchor={data.length > 6 ? 'end' : 'middle'}
              height={data.length > 6 ? 64 : 30}
            />
            <YAxis tickFormatter={compact} {...AXIS} width={52} />
            <Tooltip content={<ChartTooltip />} cursor={{ fillOpacity: 0.08 }} />
            {keys.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
            {keys.map((key, i) => (
              <Bar
                key={key}
                dataKey={key}
                fill={SERIES_COLORS[i % SERIES_COLORS.length]}
                radius={[3, 3, 0, 0]}
              />
            ))}
          </BarChart>
        ) : spec.type === 'pie' ? (
          <PieChart>
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Pie
              data={data}
              dataKey={spec.y[0]}
              nameKey={spec.x ?? undefined}
              outerRadius="75%"
              label={(entry: any) => String(entry[spec.x ?? ''] ?? '')}
              labelLine={false}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        ) : (
          <ScatterChart margin={{ top: 8, right: 16, bottom: 12, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} />
            <XAxis
              type="number"
              dataKey={spec.x ?? undefined}
              name={spec.x ?? ''}
              tickFormatter={compact}
              {...AXIS}
            />
            <YAxis
              type="number"
              dataKey={spec.y[0]}
              name={spec.y[0]}
              tickFormatter={compact}
              width={52}
              {...AXIS}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip content={<ChartTooltip />} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={data} fill={SERIES_COLORS[0]} fillOpacity={0.7} />
          </ScatterChart>
        )}
      </ResponsiveContainer>

      {analysis?.outliers.total ? (
        <p className="mt-1 text-[11px] text-data-amber">
          {analysis.outliers.total} outlying{' '}
          {analysis.outliers.total === 1 ? 'value' : 'values'} in this result - see
          the statistics panel.
        </p>
      ) : null}
    </div>
  )
}
