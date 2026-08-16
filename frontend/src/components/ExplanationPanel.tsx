/** Query explanation walkthrough (F21).
 *
 *  Two independent readings sit side by side here: the model's prose, and a
 *  step list derived mechanically from the parsed SQL. Where they disagree,
 *  something is wrong — and that is exactly what this panel exists to make
 *  visible, so it does not try to reconcile them.
 */

import type { Explanation } from '@/api/types'
import { Icon } from '@/components/icons'

const CLAUSE_TONE: Record<string, string> = {
  FROM: 'bg-secondary-container text-on-secondary-container',
  JOIN: 'bg-secondary-container text-on-secondary-container',
  WHERE: 'bg-data-amber/10 text-data-amber',
  HAVING: 'bg-data-amber/10 text-data-amber',
  'GROUP BY': 'bg-success-container text-sql-syntax-string',
  SELECT: 'bg-success-container text-sql-syntax-string',
  'ORDER BY': 'bg-surface-variant text-on-surface-variant',
  LIMIT: 'bg-error-container text-error',
}

export function ExplanationPanel({
  explanation,
  modelExplanation,
}: {
  explanation: Explanation
  modelExplanation?: string
}) {
  if (!explanation.parsed) return null

  return (
    <details className="group border-t border-subtle pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-label-md text-on-surface-variant transition-colors hover:text-on-surface">
        <Icon
          name="chevron_right"
          size={16}
          className="transition-transform group-open:rotate-90"
        />
        Walk me through this query
        <span className="ml-2 font-mono normal-case tracking-normal text-outline">
          {explanation.steps.length} steps
        </span>
      </summary>

      <div className="mt-3 space-y-3">
        <p className="text-body-md text-on-surface-variant">
          {explanation.summary}
        </p>

        <ol className="space-y-2">
          {explanation.steps.map((step) => (
            <li
              key={`${step.clause}-${step.order}`}
              className="flex gap-3 rounded-md border border-subtle bg-surface-bg p-3"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-container-high font-mono text-[11px] text-on-surface-variant">
                {step.order}
              </span>
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                      CLAUSE_TONE[step.clause] ??
                      'bg-surface-variant text-on-surface-variant'
                    }`}
                  >
                    {step.clause}
                  </span>
                  <span className="text-label-md text-on-surface">
                    {step.title}
                  </span>
                </div>
                <p className="text-body-md text-on-surface-variant">
                  {step.detail}
                </p>
                {step.sql && (
                  <code className="mt-1.5 block overflow-x-auto whitespace-pre rounded bg-surface-container-low px-2 py-1 font-mono text-[11px] text-on-surface-variant">
                    {step.sql}
                  </code>
                )}
              </div>
            </li>
          ))}
        </ol>

        {modelExplanation && (
          <div className="rounded-md border border-subtle p-3">
            <p className="mb-1 text-label-md uppercase tracking-wider text-on-surface-variant">
              What the model said it wrote
            </p>
            <p className="text-body-md text-on-surface-variant">
              {modelExplanation}
            </p>
            <p className="mt-1.5 text-[11px] text-outline">
              The steps above are read from the SQL itself. This paragraph is
              the model describing its own intent — if the two disagree, trust
              the steps.
            </p>
          </div>
        )}
      </div>
    </details>
  )
}
