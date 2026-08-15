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
