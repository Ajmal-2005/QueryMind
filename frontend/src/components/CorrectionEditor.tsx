/** Fix the SQL and teach the system (F22).
 *
 *  The correction is saved only if it passes the gates and runs - the server
 *  enforces that, and the error comes back here. A correction that was taken
 *  on trust would propagate a mistake into every future answer instead of
 *  fixing one.
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { saveCorrection } from '@/api/learning'
import { Icon } from '@/components/icons'
import { Alert, Button } from '@/components/ui'

export function CorrectionEditor({
  connectionId,
  question,
  originalSql,
  queryId,
}: {
  connectionId: string
  question: string
  originalSql: string
  queryId?: string | null
}) {
  const [open, setOpen] = useState(false)
  const [sql, setSql] = useState(originalSql)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const save = useMutation({
    mutationFn: () =>
      saveCorrection({
        connection_id: connectionId,
        question,
        corrected_sql: sql,
        original_sql: originalSql,
        query_id: queryId ?? null,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      setSaved(true)
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['corrections'] })
    },
  })

  if (saved) {
    return (
      <p className="flex items-center gap-1.5 text-body-md text-sql-syntax-string">
        <Icon name="school" size={16} fill />
        Saved. Questions like this one will use your version from now on.
      </p>
    )
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 text-label-md text-on-surface-variant transition-colors hover:text-primary"
      >
        <Icon name="edit" size={14} />
        This SQL is wrong - fix it
      </button>
    )
  }

  return (
    <div className="space-y-2 rounded-md border border-subtle bg-surface-bg p-3">
      <p className="text-label-md uppercase tracking-wider text-on-surface-variant">
        Correct the SQL
      </p>

      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        rows={6}
        spellCheck={false}
        className="w-full resize-y rounded-md border border-outline-variant bg-surface-container-lowest p-3 font-mono text-[12px] text-on-surface focus:border-data-indigo focus:outline-none"
      />

      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Optional: what was wrong with the original?"
        className="w-full rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface placeholder:text-outline focus:border-data-indigo focus:outline-none"
      />

      {save.error && (
        <Alert>{errorMessage(save.error, 'The correction was not accepted')}</Alert>
      )}

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          icon="school"
          busy={save.isPending}
          disabled={!sql.trim() || sql.trim() === originalSql.trim()}
          onClick={() => save.mutate()}
        >
          Save correction
        </Button>
        <Button size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <span className="text-[11px] text-outline">
          It must pass the safety gates and run before it is saved.
        </span>
      </div>
    </div>
  )
}
