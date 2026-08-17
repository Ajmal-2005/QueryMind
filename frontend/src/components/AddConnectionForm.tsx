import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { createConnection } from '@/api/connections'
import type { Dialect } from '@/api/types'
import { Icon } from '@/components/icons'
import { Alert, Button, Field, Input, Select } from '@/components/ui'

const DIALECTS: { value: Dialect; label: string; defaultPort: number }[] = [
  { value: 'postgres', label: 'PostgreSQL', defaultPort: 5432 },
  { value: 'mysql', label: 'MySQL', defaultPort: 3306 },
  { value: 'sqlite', label: 'SQLite (file)', defaultPort: 0 },
]

export function AddConnectionDialog({ onClose }: { onClose: () => void }) {
  const [dialect, setDialect] = useState<Dialect>('sqlite')
  const [name, setName] = useState('')
  const [database, setDatabase] = useState('')
  const [host, setHost] = useState('localhost')
  const [port, setPort] = useState('5432')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const queryClient = useQueryClient()
  const isFile = dialect === 'sqlite'

  // Escape closes the dialog, as it does in every other dialog the user has
  // ever used.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const mutation = useMutation({
    mutationFn: createConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connections'] })
      onClose()
    },
    onError: (err) => setError(errorMessage(err, 'Could not save the connection')),
  })

  function handleDialectChange(next: Dialect) {
    setDialect(next)
    const preset = DIALECTS.find((d) => d.value === next)
    if (preset?.defaultPort) setPort(String(preset.defaultPort))
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    // A file-backed database has no host, port, or credentials. Send port as
    // null rather than 0 - the API validates it as a real port number when
    // present, and 0 is not one.
    mutation.mutate(
      isFile
        ? { name, dialect, database, port: null }
        : { name, dialect, database, host, port: Number(port), username, password },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:items-center">
      <div
        className="fixed inset-0 bg-on-surface/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-connection-title"
        className="relative w-full max-w-lg animate-fade-in rounded-xl border border-subtle bg-surface-container-lowest shadow-lift"
      >
        <div className="flex items-start gap-3 border-b border-subtle px-6 py-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-secondary-container text-on-secondary-container">
            <Icon name="cloud_sync" size={20} />
          </div>
          <div className="min-w-0">
            <h3 id="add-connection-title" className="text-headline-sm text-primary">
              Add a database connection
            </h3>
            <p className="mt-0.5 text-body-md text-on-surface-variant">
              Credentials are encrypted before storage and never returned by the API.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 px-6 py-5 sm:grid-cols-2">
            <Field label="DATABASE TYPE">
              <Select
                value={dialect}
                onChange={(e) => handleDialectChange(e.target.value as Dialect)}
              >
                {DIALECTS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="DISPLAY NAME">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="Production DB Main"
              />
            </Field>

            <Field
              label={isFile ? 'DATABASE FILE PATH' : 'DATABASE NAME'}
              className="sm:col-span-2"
            >
              <Input
                value={database}
                onChange={(e) => setDatabase(e.target.value)}
                required
                placeholder={isFile ? 'C:\\path\\to\\demo_ecommerce.db' : 'analytics'}
                className="font-mono text-code-sm"
              />
            </Field>

            {!isFile && (
              <>
                <Field label="HOST">
                  <Input
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    required
                  />
                </Field>
                <Field label="PORT">
                  <Input
                    type="number"
                    value={port}
                    onChange={(e) => setPort(e.target.value)}
                    required
                  />
                </Field>
                <Field label="USERNAME">
                  <Input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </Field>
                <Field label="PASSWORD">
                  <Input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                  />
                </Field>
              </>
            )}

            {error && (
              <div className="sm:col-span-2">
                <Alert>{error}</Alert>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 border-t border-subtle bg-surface-bg px-6 py-4">
            <Button type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={mutation.isPending} icon="add">
              Save connection
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
