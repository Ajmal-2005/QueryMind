import { useMemo, useState } from 'react'

import { Icon } from '@/components/icons'

const KEYWORDS = [
  'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT',
  'OFFSET', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'OUTER JOIN',
  'CROSS JOIN', 'ON', 'AS', 'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN',
  'LIKE', 'IS NULL', 'IS NOT NULL', 'WITH', 'UNION', 'ALL', 'DISTINCT',
  'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'ASC', 'DESC', 'COUNT', 'SUM',
  'AVG', 'MIN', 'MAX', 'ROUND', 'COALESCE', 'CAST', 'OVER', 'PARTITION BY',
]

// Longest-first so "LEFT JOIN" wins over "JOIN".
const KEYWORD_RE = new RegExp(
  `\\b(${[...KEYWORDS].sort((a, b) => b.length - a.length).join('|')})\\b`,
  'gi',
)
const STRING_RE = /'[^']*'/g
const NUMBER_RE = /\b\d+(\.\d+)?\b/g

type Token = { text: string; kind: 'keyword' | 'string' | 'number' | 'plain' }

/** Minimal SQL tokenizer for display.
 *
 *  Deliberately not a parser — highlighting is a readability aid, and the
 *  authoritative parse happens server-side with sqlglot in phase 3.
 */
function tokenize(sql: string): Token[] {
  const marks: { start: number; end: number; kind: Token['kind'] }[] = []

  const collect = (re: RegExp, kind: Token['kind']) => {
    for (const match of sql.matchAll(re)) {
      const start = match.index ?? 0
      // Strings win over anything inside them.
      if (marks.some((m) => start >= m.start && start < m.end)) continue
      marks.push({ start, end: start + match[0].length, kind })
    }
  }

  collect(STRING_RE, 'string')
  collect(KEYWORD_RE, 'keyword')
  collect(NUMBER_RE, 'number')
  marks.sort((a, b) => a.start - b.start)

  const tokens: Token[] = []
  let cursor = 0
  for (const mark of marks) {
    if (mark.start < cursor) continue
    if (mark.start > cursor) {
      tokens.push({ text: sql.slice(cursor, mark.start), kind: 'plain' })
    }
    tokens.push({ text: sql.slice(mark.start, mark.end), kind: mark.kind })
    cursor = mark.end
  }
  if (cursor < sql.length) tokens.push({ text: sql.slice(cursor), kind: 'plain' })

  return tokens
}

const TOKEN_CLASS: Record<Token['kind'], string> = {
  keyword: 'text-sql-syntax-keyword font-medium',
  string: 'text-sql-syntax-string',
  number: 'text-data-amber',
  plain: '',
}

export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false)
  const tokens = useMemo(() => tokenize(sql), [sql])

  async function copy() {
    await navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="relative overflow-hidden rounded-md border border-subtle bg-surface-bg">
      <div className="flex items-center justify-between border-b border-subtle px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-label-md uppercase tracking-wider text-on-surface-variant">
          <Icon name="code" size={14} />
          Generated SQL
        </span>
        <button
          onClick={copy}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-label-md text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-primary"
        >
          <Icon name={copied ? 'check' : 'content_copy'} size={14} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 font-mono text-code-sm leading-relaxed text-on-surface">
        {tokens.map((token, i) => (
          <span key={i} className={TOKEN_CLASS[token.kind]}>
            {token.text}
          </span>
        ))}
      </pre>
    </div>
  )
}
