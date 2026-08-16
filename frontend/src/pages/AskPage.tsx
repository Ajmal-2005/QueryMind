import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { listConnections } from '@/api/connections'
import { askQuestion } from '@/api/query'
import type { Connection, QueryResponse, QuestionType } from '@/api/types'
import { Icon } from '@/components/icons'
import { ResultTable } from '@/components/ResultTable'
import { SqlBlock } from '@/components/SqlBlock'
import { Alert, EmptyState, Pill, Select, Spinner } from '@/components/ui'

interface Turn {
  id: string
  question: string
  response?: QueryResponse
  error?: string
}

const TYPE_LABEL: Record<QuestionType, string> = {
  aggregation: 'Aggregation',
  comparison: 'Comparison',
  trend: 'Trend',
  ranking: 'Ranking',
  filter: 'Lookup',
  ambiguous: 'Ambiguous',
}

const STARTERS = [
  'How many customers do we have?',
  'Top 5 products by price',
  'What was total revenue last quarter?',
  'Which customers have never placed an order?',
]

export function AskPage() {
  const [connectionId, setConnectionId] = useState<string>('')
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  // One session per page visit, so follow-ups resolve against this
  // conversation and not someone else's.
  const [sessionId] = useState(() => crypto.randomUUID())
  const endRef = useRef<HTMLDivElement>(null)

  const { data: connections } = useQuery({
    queryKey: ['connections'],
    queryFn: listConnections,
  })

  const indexed = (connections ?? []).filter(
    (c: Connection) => c.status === 'indexed',
  )

  useEffect(() => {
    if (!connectionId && indexed.length > 0) setConnectionId(indexed[0].id)
  }, [connectionId, indexed])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  const ask = useMutation({
    mutationFn: (text: string) =>
      askQuestion({
        connection_id: connectionId,
        question: text,
        session_id: sessionId,
      }),
    onSuccess: (response, text) =>
      setTurns((prev) =>
        prev.map((t) =>
          t.question === text && !t.response && !t.error ? { ...t, response } : t,
        ),
      ),
    onError: (err, text) =>
      setTurns((prev) =>
        prev.map((t) =>
          t.question === text && !t.response && !t.error
            ? { ...t, error: errorMessage(err, 'Could not answer that') }
            : t,
        ),
      ),
  })

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !connectionId || ask.isPending) return
    setTurns((prev) => [...prev, { id: crypto.randomUUID(), question: trimmed }])
    setQuestion('')
    ask.mutate(trimmed)
  }

  if (indexed.length === 0) {
    return (
      <EmptyState
        icon="database"
        title="No indexed database yet"
        description="Add a connection and index its schema, then come back here to ask questions of it."
      />
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="mb-2 text-headline-lg-mobile text-primary md:text-headline-lg">
            Ask
          </h2>
          <p className="max-w-2xl text-body-lg text-on-surface-variant">
            Ask a question in plain English. The engine retrieves the relevant
            tables and writes the SQL.
          </p>
        </div>

        <label className="text-label-md text-on-surface-variant">
          <span className="mb-1.5 block uppercase tracking-wider">Database</span>
          <Select
            value={connectionId}
            onChange={(e) => setConnectionId(e.target.value)}
            className="min-w-[14rem]"
          >
            {indexed.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      <div className="flex-1 space-y-6">
        {turns.length === 0 && (
          <div className="rounded-xl border border-dashed border-subtle p-6">
            <p className="text-label-md uppercase tracking-wider text-on-surface-variant">
              Try one of these
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  onClick={() => submit(starter)}
                  className="rounded-full border border-subtle bg-surface-container-lowest px-3 py-1.5 text-body-md text-on-surface-variant transition-colors hover:border-primary hover:text-primary"
                >
                  {starter}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}

        {ask.isPending && (
          <div className="flex items-center gap-2 text-body-md text-on-surface-variant">
            <Spinner />
            Retrieving schema and generating SQL…
          </div>
        )}

        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit(question)
        }}
        className="sticky bottom-0 mt-6 bg-gradient-to-t from-surface-bg via-surface-bg pb-2 pt-6"
      >
        <div className="relative">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter is a newline — the convention every
              // chat surface uses.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit(question)
              }
            }}
            rows={2}
            placeholder="Ask a question about your data…"
            className="w-full resize-none rounded-xl border-2 border-subtle bg-surface-container-lowest p-4 pr-16 text-body-lg text-on-surface shadow-card transition-colors placeholder:text-outline focus:border-primary focus:outline-none"
          />
          <button
            type="submit"
            disabled={!question.trim() || ask.isPending}
            aria-label="Send question"
            className="absolute bottom-3 right-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-on-primary transition-opacity hover:bg-opacity-90 disabled:opacity-40"
          >
            <Icon name="auto_awesome" size={20} fill />
          </button>
        </div>
      </form>
    </div>
  )
}

function TurnView({ turn }: { turn: Turn }) {
  const { response } = turn

  return (
    <div className="animate-fade-in space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-xl border border-subtle bg-surface-container-lowest p-4 shadow-card">
          <div className="mb-2 flex items-center gap-2 text-on-surface-variant">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-variant">
              <Icon name="person" size={14} />
            </span>
            <span className="text-label-md">You</span>
          </div>
          <p className="text-body-lg text-on-surface">{turn.question}</p>
        </div>
      </div>

      <div className="rounded-xl border border-subtle bg-surface-container-lowest shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-secondary-container text-on-secondary-container">
              <Icon name="auto_awesome" size={16} fill />
            </span>
            <span className="text-label-md text-on-surface">Syntactic AI</span>
          </div>
          {response && (
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="indigo" dot={false}>
                {TYPE_LABEL[response.question_type]}
              </Pill>
              {response.timings_ms.total !== undefined && (
                <span className="font-mono text-[11px] text-outline">
                  {Math.round(response.timings_ms.total)} ms
                </span>
              )}
            </div>
          )}
        </div>

        <div className="space-y-4 p-5">
          {turn.error && <Alert>{turn.error}</Alert>}
          {!turn.error && !response && (
            <p className="flex items-center gap-2 text-body-md text-on-surface-variant">
              <Spinner /> Thinking…
            </p>
          )}

          {response?.needs_clarification && (
            <p className="flex items-start gap-2 text-body-lg text-on-surface">
              <Icon name="help" size={18} className="mt-0.5 text-data-amber" />
              {response.clarification}
            </p>
          )}

          {response?.rejected && (
            <div className="rounded-md border border-error/25 bg-error-container p-4">
              <p className="mb-1 flex items-center gap-1.5 text-label-md uppercase tracking-wider text-error">
                <Icon name="gpp_bad" size={16} />
                Blocked by the {response.validation?.gate} gate
              </p>
              <p className="text-body-md text-error">{response.error}</p>
              <p className="mt-2 text-body-md text-on-surface-variant">
                This query was refused outright and not retried. The connection
                is read-only, so it could not have run in any case.
              </p>
            </div>
          )}

          {response?.error && !response.rejected && <Alert>{response.error}</Alert>}

          {response?.generation && !response.rejected && (
            <>
              <p className="text-body-lg text-on-surface">
                {response.generation.explanation}
              </p>

              {response.result && <ResultTable result={response.result} />}

              <SqlBlock sql={response.validation?.sql || response.generation.sql} />

              {response.validation?.warnings.map((warning) => (
                <p
                  key={warning}
                  className="flex items-center gap-1.5 text-body-md text-on-surface-variant"
                >
                  <Icon name="info" size={14} />
                  {warning}
                </p>
              ))}

              {response.recovered_by_correction && (
                <p className="flex items-center gap-1.5 text-body-md text-sql-syntax-string">
                  <Icon name="auto_fix_high" size={14} />
                  Repaired after {response.correction_attempts}{' '}
                  {response.correction_attempts === 1 ? 'attempt' : 'attempts'} using
                  the database's own error message.
                </p>
              )}

              {response.generation.assumptions.length > 0 && (
                <div className="rounded-md border border-data-amber/25 bg-data-amber/5 p-3">
                  <p className="mb-1 flex items-center gap-1.5 text-label-md uppercase tracking-wider text-data-amber">
                    <Icon name="info" size={14} />
                    Assumptions
                  </p>
                  <ul className="space-y-1 text-body-md text-on-surface-variant">
                    {response.generation.assumptions.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              <Provenance response={response} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** What the model was shown, and how confident it is.
 *
 *  The proposal makes transparency a hard requirement: the SQL is always
 *  visible, and so is the table set it was written against.
 */
function Provenance({ response }: { response: QueryResponse }) {
  const generation = response.generation!
  const confidence = Math.round(generation.confidence * 100)
  const tone =
    confidence >= 70 ? 'text-sql-syntax-string' : confidence >= 40 ? 'text-data-amber' : 'text-error'

  return (
    <details className="group border-t border-subtle pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-label-md text-on-surface-variant transition-colors hover:text-on-surface">
        <Icon
          name="chevron_right"
          size={16}
          className="transition-transform group-open:rotate-90"
        />
        How this was built
        <span className={`ml-2 font-mono normal-case tracking-normal ${tone}`}>
          {confidence}% confidence
        </span>
      </summary>

      <div className="mt-3 space-y-3 text-body-md">
        <div>
          <p className="mb-1.5 text-label-md uppercase tracking-wider text-on-surface-variant">
            Tables retrieved
          </p>
          <div className="flex flex-wrap gap-1.5">
            {response.retrieved_tables.map((table) => (
              <span
                key={table.table_name}
                title={
                  table.via_expansion
                    ? 'Added by foreign-key expansion to keep the joins valid'
                    : `Ranked #${(table.dense_rank ?? 0) + 1} dense, #${(table.sparse_rank ?? 0) + 1} keyword`
                }
                className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${
                  table.via_expansion
                    ? 'bg-surface-variant text-on-surface-variant'
                    : 'bg-secondary-container text-on-secondary-container'
                }`}
              >
                {table.table_name}
                {table.via_expansion && ' ↳'}
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-outline">
            ↳ pulled in by foreign-key expansion, not by relevance ranking
          </p>
        </div>

        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-on-surface-variant">
          <span>
            model <span className="font-mono text-on-surface">{generation.model}</span>
          </span>
          {response.embedder && (
            <span>
              embedder <span className="font-mono text-on-surface">{response.embedder}</span>
            </span>
          )}
          <span>
            tokens{' '}
            <span className="font-mono text-on-surface">
              {generation.input_tokens + generation.output_tokens}
            </span>
          </span>
          {Object.entries(response.timings_ms)
            .filter(([stage]) => stage !== 'total')
            .map(([stage, ms]) => (
              <span key={stage}>
                {stage} <span className="font-mono text-on-surface">{Math.round(ms)} ms</span>
              </span>
            ))}
        </dl>
      </div>
    </details>
  )
}
