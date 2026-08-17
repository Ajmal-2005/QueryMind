/** Business glossary (F24) and saved corrections (F22).
 *
 *  Both are the same idea from two directions - things this deployment knows
 *  that the schema does not - so they share a page. A glossary term is an
 *  explicit definition; a correction is one learned by being told.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { listConnections } from '@/api/connections'
import {
  deleteCorrection,
  deleteTerm,
  listCorrections,
  listGlossary,
  saveTerm,
} from '@/api/learning'
import type { Connection } from '@/api/types'
import { Icon } from '@/components/icons'
import { Alert, Button, EmptyState, Field, Input, Select, Skeleton } from '@/components/ui'

export function GlossaryPage() {
  const [connectionId, setConnectionId] = useState('')
  const queryClient = useQueryClient()

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

  const { data: terms, isPending } = useQuery({
    queryKey: ['glossary', connectionId],
    queryFn: () => listGlossary(connectionId),
    enabled: Boolean(connectionId),
  })

  const { data: corrections } = useQuery({
    queryKey: ['corrections', connectionId],
    queryFn: () => listCorrections(connectionId),
    enabled: Boolean(connectionId),
  })

  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [expression, setExpression] = useState('')

  const save = useMutation({
    mutationFn: () =>
      saveTerm({
        connection_id: connectionId,
        term: term.trim(),
        definition: definition.trim(),
        sql_expression: expression.trim() || null,
      }),
    onSuccess: () => {
      setTerm('')
      setDefinition('')
      setExpression('')
      queryClient.invalidateQueries({ queryKey: ['glossary', connectionId] })
    },
  })

  const removeTerm = useMutation({
    mutationFn: deleteTerm,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['glossary', connectionId] }),
  })

  const removeCorrection = useMutation({
    mutationFn: deleteCorrection,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['corrections', connectionId] }),
  })

  if (indexed.length === 0) {
    return (
      <EmptyState
        icon="menu_book"
        title="No indexed database yet"
        description="Add a connection and index its schema, then define what your business terms mean."
      />
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="mb-2 text-headline-lg-mobile text-primary md:text-headline-lg">
            Glossary
          </h2>
          <p className="max-w-2xl text-body-lg text-on-surface-variant">
            “Active customer” is not in any schema. Define it here and every
            query uses your definition instead of guessing at one.
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

      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (term.trim() && definition.trim()) save.mutate()
        }}
        className="space-y-3 rounded-xl border border-subtle bg-surface-container-lowest p-5 shadow-card"
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Term">
            <Input
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="active customer"
            />
          </Field>
          <Field label="Means">
            <Input
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
              placeholder="a customer who has ordered in the last 90 days"
            />
          </Field>
        </div>

        <Field
          label="SQL expression (optional)"
          hint="A fragment, not a statement - no semicolons or comments."
        >
          <Input
            value={expression}
            onChange={(e) => setExpression(e.target.value)}
            placeholder="o.created_at >= date('now', '-90 days')"
            className="font-mono text-[12px]"
          />
        </Field>

        {save.error && (
          <Alert>{errorMessage(save.error, 'Could not save that term')}</Alert>
        )}

        <Button
          type="submit"
          variant="primary"
          icon="add"
          busy={save.isPending}
          disabled={!term.trim() || !definition.trim()}
        >
          Save definition
        </Button>
      </form>

      <section>
        <h3 className="mb-3 text-headline-sm text-primary">Defined terms</h3>
        {isPending ? (
          <Skeleton className="h-24" />
        ) : terms && terms.length > 0 ? (
          <div className="divide-y divide-subtle overflow-hidden rounded-xl border border-subtle">
            {terms.map((entry) => (
              <div
                key={entry.id}
                className="group flex items-start gap-3 bg-surface-container-lowest p-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-label-md text-on-surface">{entry.term}</p>
                  <p className="text-body-md text-on-surface-variant">
                    {entry.definition}
                  </p>
                  {entry.sql_expression && (
                    <code className="mt-1 block overflow-x-auto rounded bg-surface-container-low px-2 py-1 font-mono text-[11px] text-on-surface-variant">
                      {entry.sql_expression}
                    </code>
                  )}
                </div>
                <button
                  onClick={() => removeTerm.mutate(entry.id)}
                  aria-label={`Delete ${entry.term}`}
                  className="shrink-0 rounded p-1 text-outline opacity-0 transition-opacity hover:bg-error-container hover:text-error group-hover:opacity-100"
                >
                  <Icon name="delete" size={16} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-subtle p-6 text-center text-body-md text-on-surface-variant">
            No terms yet. Anything your team says that the schema does not spell
            out belongs here.
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-1 text-headline-sm text-primary">Your corrections</h3>
        <p className="mb-3 text-body-md text-on-surface-variant">
          SQL you fixed by hand. These are shown to the model as examples ahead
          of anything it merely got right on its own.
        </p>

        {corrections && corrections.length > 0 ? (
          <div className="divide-y divide-subtle overflow-hidden rounded-xl border border-subtle">
            {corrections.map((correction) => (
              <div
                key={correction.id}
                className="group flex items-start gap-3 bg-surface-container-lowest p-4"
              >
                <Icon
                  name="school"
                  size={16}
                  className="mt-0.5 shrink-0 text-sql-syntax-string"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-body-md text-on-surface">
                    {correction.question}
                  </p>
                  <code className="mt-1 block overflow-x-auto whitespace-pre rounded bg-surface-container-low px-2 py-1 font-mono text-[11px] text-on-surface-variant">
                    {correction.corrected_sql}
                  </code>
                  {correction.note && (
                    <p className="mt-1 text-[12px] text-outline">
                      {correction.note}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => removeCorrection.mutate(correction.id)}
                  aria-label="Forget this correction"
                  className="shrink-0 rounded p-1 text-outline opacity-0 transition-opacity hover:bg-error-container hover:text-error group-hover:opacity-100"
                >
                  <Icon name="delete" size={16} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-subtle p-6 text-center text-body-md text-on-surface-variant">
            Nothing yet. When a query comes back wrong, use “This SQL is wrong -
            fix it” on the answer.
          </p>
        )}
      </section>
    </div>
  )
}
