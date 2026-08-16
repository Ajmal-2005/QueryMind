export type UserRole = 'admin' | 'analyst' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export type ServiceStatus = 'ok' | 'degraded' | 'unavailable' | 'not_configured'

export interface ServiceHealth {
  status: ServiceStatus
  detail: string | null
  latency_ms: number | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  environment: string
  services: Record<string, ServiceHealth>
}

export type Dialect = 'postgres' | 'mysql' | 'sqlite'

export type ConnectionStatus =
  | 'pending'
  | 'connected'
  | 'indexing'
  | 'indexed'
  | 'failed'

export interface Connection {
  id: string
  name: string
  dialect: Dialect
  host: string
  port: number
  database: string
  status: ConnectionStatus
  last_error: string | null
  last_indexed_at: string | null
  created_at: string
}

export interface ConnectionCreate {
  name: string
  dialect: Dialect
  database: string
  host?: string
  port?: number | null
  username?: string
  password?: string
}

export interface ConnectionTestResult {
  ok: boolean
  latency_ms: number
  server_version: string | null
  error: string | null
}

export interface IndexResult {
  connection_id: string
  tables_indexed: number
  columns_indexed: number
  foreign_keys: number
  isolated_tables: number
  embedder: string
  introspection_ms: number
  embedding_ms: number
  total_ms: number
}

export interface SchemaColumn {
  column_name: string
  data_type: string
  is_nullable: boolean
  is_pk: boolean
  is_indexed: boolean
  fk_target: string | null
  sample_values: string[] | null
}

export interface SchemaTable {
  id: string
  table_name: string
  schema_name: string | null
  description: string
  row_estimate: number | null
  columns: SchemaColumn[]
}

export interface SchemaEdge {
  from_table: string
  to_table: string
}

export interface SchemaResponse {
  connection_id: string
  table_count: number
  column_count: number
  tables: SchemaTable[]
  edges: SchemaEdge[]
  isolated_tables: string[]
}

export type QuestionType =
  | 'aggregation'
  | 'comparison'
  | 'trend'
  | 'ranking'
  | 'filter'
  | 'ambiguous'

export interface RetrievedTable {
  table_name: string
  score: number
  via_expansion: boolean
  dense_rank: number | null
  sparse_rank: number | null
}

export interface Generation {
  sql: string
  confidence: number
  explanation: string
  assumptions: string[]
  model: string
  input_tokens: number
  output_tokens: number
}

export interface ValidationInfo {
  ok: boolean
  sql: string
  gate: 'syntax' | 'schema' | 'safety' | 'cost' | null
  message: string | null
  retryable: boolean | null
  warnings: string[]
  limit_applied: number | null
}

export interface ResultSet {
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  duration_ms: number
}

export interface Attempt {
  number: number
  sql: string
  error: string | null
  gate: string | null
  succeeded: boolean
}

export interface QueryResponse {
  query_id: string | null
  question: string
  resolved_question: string
  question_type: QuestionType
  needs_clarification: boolean
  clarification: string | null
  rejected: boolean
  generation: Generation | null
  validation: ValidationInfo | null
  result: ResultSet | null
  attempts: Attempt[]
  correction_attempts: number
  recovered_by_correction: boolean
  retrieved_tables: RetrievedTable[]
  embedder: string | null
  error: string | null
  timings_ms: Record<string, number>
}
