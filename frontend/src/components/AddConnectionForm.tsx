import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { errorMessage } from '@/api/client'
import { createConnection } from '@/api/connections'
import type { Dialect } from '@/api/types'

const DIALECTS: { value: Dialect; label: string; defaultPort: number }[] = [
  { value: 'postgres', label: 'PostgreSQL', defaultPort: 5432 },
  { value: 'mysql', label: 'MySQL', defaultPort: 3306 },
  { value: 'sqlite', label: 'SQLite (file)', defaultPort: 0 },
]

export function AddConnectionForm({ onDone }: { onDone: () => void }) {
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

  const mutation = useMutation({
    mutationFn: createConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connections'] })
      onDone()
    },
    onError: (err) => setError(errorMessage(err, 'Could not save the connection')),
  })

  function handleDialectChange(next: Dialect) {
    setDialect(next)
    const preset = DIALECTS.find((d) => d.value === next)
    if (preset && preset.defaultPort) setPort(String(preset.defaultPort))
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    // A file-backed database has no host, port, or credentials. Send port as
    // null rather than 0 — the API validates it as a real port number when
    // present, and 0 is not one.
    mutation.mutate(
      isFile
        ? { name, dialect, database, port: null }
        : {
            name,
            dialect,
            database,
            host,
            port: Number(port),
            username,
            password,
          },
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h3 className="font-medium">Add a database connection</h3>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Type</span>
          <select
            value={dialect}
            onChange={(e) => handleDialectChange(e.target.value as Dialect)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            {DIALECTS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>

        <Input label="Display name" value={name} onChange={setName} required />

        <label className="block text-sm sm:col-span-2">
          <span className="font-medium text-slate-700">
            {isFile ? 'Database file path' : 'Database name'}
          </span>
          <input
            value={database}
            onChange={(e) => setDatabase(e.target.value)}
            required
            placeholder={isFile ? 'C:\\path\\to\\demo_ecommerce.db' : 'analytics'}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs"
          />
        </label>

        {!isFile && (
          <>
            <Input label="Host" value={host} onChange={setHost} required />
            <Input label="Port" value={port} onChange={setPort} type="number" required />
            <Input label="Username" value={username} onChange={setUsername} required />
            <Input
              label="Password"
              value={password}
              onChange={setPassword}
              type="password"
            />
          </>
        )}
      </div>

      {!isFile && (
        <p className="mt-3 text-xs text-slate-400">
          Credentials are encrypted before storage and are never returned by the API.
        </p>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-600">
          {error}
        </p>
      )}

      <div className="mt-5 flex gap-2">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {mutation.isPending ? 'Saving…' : 'Save connection'}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

interface InputProps {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  required?: boolean
}

function Input({ label, value, onChange, type = 'text', required }: InputProps) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
    </label>
  )
}
