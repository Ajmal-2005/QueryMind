/** Statistical profile (F14), outliers (F15) and trend (F16).
 *
 *  Collapsed by default. The point of the product is the answer; this is the
 *  evidence behind it, for the reader who wants to check.
 */

import type { Analysis } from '@/api/types'
import { Icon } from '@/components/icons'

function num(value: number | null, digits = 2): string {
  if (value === null || value === undefined) return '-'
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: digits })
}

const KIND_TONE: Record<string, string> = {
  numeric: 'text-data-indigo',
  temporal: 'text-sql-syntax-string',
  categorical: 'text-data-amber',
  boolean: 'text-data-amber',
  text: 'text-on-surface-variant',
  empty: 'text-outline',
}

export function ProfilePanel({ analysis }: { analysis: Analysis }) {
  const { profile, outliers, trend } = analysis

  return (
    <details className="group border-t border-subtle pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-label-md text-on-surface-variant transition-colors hover:text-on-surface">
        <Icon
          name="chevron_right"
          size={16}
          className="transition-transform group-open:rotate-90"
        />
        Statistics
        <span className="ml-2 font-mono normal-case tracking-normal text-outline">
          {profile.row_count.toLocaleString()} × {profile.column_count}
          {outliers.total > 0 && (
            <span className="ml-2 text-data-amber">
              {outliers.total} outlier{outliers.total === 1 ? '' : 's'}
            </span>
          )}
        </span>
      </summary>

      <div className="mt-3 space-y-4">
        {trend && (
          <div className="rounded-md border border-subtle bg-surface-bg p-3">
            <p className="mb-1 flex items-center gap-1.5 text-label-md uppercase tracking-wider text-on-surface-variant">
              <Icon
                name={
                  trend.direction === 'rising'
                    ? 'trending_up'
                    : trend.direction === 'falling'
                      ? 'trending_down'
                      : 'trending_flat'
                }
                size={15}
              />
              Trend
            </p>
            <p className="text-body-md text-on-surface">{trend.summary}</p>
            <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-on-surface-variant">
              <span>
                total change{' '}
                <span className="font-mono text-on-surface">
                  {num(trend.total_change)}
                </span>
              </span>
              {trend.average_growth_rate !== null && (
                <span>
                  avg period change{' '}
                  <span className="font-mono text-on-surface">
                    {(trend.average_growth_rate * 100).toFixed(1)}%
                  </span>
                </span>
              )}
              <span>
                best <span className="font-mono text-on-surface">{trend.best_period}</span>
              </span>
              <span>
                worst{' '}
                <span className="font-mono text-on-surface">{trend.worst_period}</span>
              </span>
              <span>
                {trend.window}-period moving average computed
              </span>
            </dl>
          </div>
        )}

        {!trend && analysis.trend_unavailable && (
          <p className="text-[12px] text-outline">
            No trend: {analysis.trend_unavailable}.
          </p>
        )}

        <div className="overflow-x-auto rounded-md border border-subtle">
          <table className="w-full border-collapse text-left text-body-md">
            <thead className="border-b border-subtle bg-surface-bg text-label-md uppercase tracking-wider text-on-surface-variant">
              <tr>
                <th className="px-3 py-2">Column</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2 text-right">Nulls</th>
                <th className="px-3 py-2 text-right">Distinct</th>
                <th className="px-3 py-2 text-right">Min</th>
                <th className="px-3 py-2 text-right">Median</th>
                <th className="px-3 py-2 text-right">Max</th>
                <th className="px-3 py-2 text-right">Mean</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle text-on-surface">
              {profile.columns.map((column) => (
                <tr key={column.name}>
                  <td className="px-3 py-1.5 font-mono text-[12px]">{column.name}</td>
                  <td
                    className={`px-3 py-1.5 text-[12px] ${KIND_TONE[column.kind]}`}
                    title={column.inferred_from}
                  >
                    {column.kind}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {column.null_count
                      ? `${column.null_count} (${(column.null_fraction * 100).toFixed(0)}%)`
                      : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {column.distinct_count.toLocaleString()}
                  </td>
                  {column.kind === 'temporal' ? (
                    <>
                      <td className="px-3 py-1.5 text-right font-mono text-[12px]">
                        {column.earliest}
                      </td>
                      <td className="px-3 py-1.5 text-right text-outline">-</td>
                      <td className="px-3 py-1.5 text-right font-mono text-[12px]">
                        {column.latest}
                      </td>
                      <td className="px-3 py-1.5 text-right text-outline">-</td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                        {num(column.minimum)}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                        {num(column.median)}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                        {num(column.maximum)}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                        {num(column.mean)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {outliers.total > 0 && (
          <div className="rounded-md border border-data-amber/25 bg-data-amber/5 p-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-label-md uppercase tracking-wider text-data-amber">
              <Icon name="warning" size={14} />
              {outliers.total} outlier{outliers.total === 1 ? '' : 's'}
            </p>
            <ul className="space-y-1 text-body-md text-on-surface-variant">
              {outliers.outliers.slice(0, 6).map((outlier) => (
                <li key={`${outlier.column}-${outlier.row_index}`}>
                  <span className="font-mono text-on-surface">
                    {outlier.column} = {num(outlier.value)}
                  </span>{' '}
                  in row {outlier.row_index + 1} -{' '}
                  {outlier.methods.length === 2
                    ? 'flagged by both the IQR and z-score tests'
                    : `flagged by ${outlier.methods[0] === 'iqr' ? 'the IQR rule' : 'the z-score'} only`}
                  {outlier.z_score !== null && (
                    <span className="text-outline"> (z = {outlier.z_score.toFixed(1)})</span>
                  )}
                </li>
              ))}
            </ul>
            {outliers.truncated && (
              <p className="mt-1 text-[11px] text-outline">
                Showing the most extreme; more were found.
              </p>
            )}
          </div>
        )}
      </div>
    </details>
  )
}
