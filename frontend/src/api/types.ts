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
  cached: boolean
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
  clarification_options: string[]
  rejected: boolean
  generation: Generation | null
  validation: ValidationInfo | null
  result: ResultSet | null
  analysis: Analysis | null
  explanation: Explanation | null
  is_follow_up: boolean
  semantic_hit: SemanticHit | null
  examples_used: UsedExample[]
  glossary_terms: GlossaryMatch[]
  attempts: Attempt[]
  correction_attempts: number
  recovered_by_correction: boolean
  retrieved_tables: RetrievedTable[]
  embedder: string | null
  error: string | null
  timings_ms: Record<string, number>
}

/* ------------------------------------------------------- analytics (phase 4) */

export type ChartType = 'line' | 'bar' | 'pie' | 'scatter' | 'kpi' | 'table'

export type ColumnKind =
  | 'numeric'
  | 'temporal'
  | 'categorical'
  | 'boolean'
  | 'text'
  | 'empty'

export type ExportFormat = 'csv' | 'json' | 'xlsx' | 'pdf'

export interface TopValue {
  value: string
  count: number
  fraction: number
}

export interface ColumnProfile {
  name: string
  kind: ColumnKind
  inferred_from: string
  count: number
  null_count: number
  null_fraction: number
  distinct_count: number
  minimum: number | null
  maximum: number | null
  mean: number | null
  median: number | null
  stddev: number | null
  q1: number | null
  q3: number | null
  earliest: string | null
  latest: string | null
  top_values: TopValue[]
}

export interface ResultProfile {
  row_count: number
  column_count: number
  truncated: boolean
  columns: ColumnProfile[]
}

export interface ChartSpec {
  type: ChartType
  reason: string
  x: string | null
  y: string[]
  series: string | null
  alternatives: ChartType[]
}

export interface Outlier {
  row_index: number
  column: string
  value: number
  methods: string[]
  z_score: number | null
  iqr_distance: number | null
}

export interface ColumnOutliers {
  column: string
  checked: boolean
  reason: string
  iqr_count: number
  zscore_count: number
  agreed_count: number
  lower_fence: number | null
  upper_fence: number | null
}

export interface OutlierReport {
  total: number
  truncated: boolean
  columns: ColumnOutliers[]
  outliers: Outlier[]
}

export interface TrendPoint {
  period: string
  value: number
  delta: number | null
  growth_rate: number | null
  moving_average: number | null
}

export interface Trend {
  period_column: string
  value_column: string
  direction: 'rising' | 'falling' | 'flat'
  summary: string
  window: number
  first_value: number
  last_value: number
  total_change: number
  total_growth_rate: number | null
  average_growth_rate: number | null
  best_period: string | null
  worst_period: string | null
  points: TrendPoint[]
}

export interface Analysis {
  profile: ResultProfile
  chart: ChartSpec
  outliers: OutlierReport
  trend: Trend | null
  trend_unavailable: string | null
  options: Record<string, string[]>
  duration_ms: number
}

export interface MaskedColumn {
  column: string
  rule: string
  detected_as: string
  values_masked: number
}

export interface Narrative {
  headline: string
  summary: string
  findings: string[]
  model: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  masked_columns: MaskedColumn[]
}

export interface CacheStatus {
  backend: string
  hits: number
  misses: number
  writes: number
  errors: number
  hit_rate: number
  ttl_seconds: number
}

/* ------------------------------------------------------ dashboards (phase 4) */

export interface Dashboard {
  id: string
  name: string
  description: string | null
  layout: Record<string, unknown>
  tile_count: number
  created_at: string
  updated_at: string
}

export interface DashboardTile {
  id: string
  title: string
  connection_id: string | null
  connection_name: string | null
  question: string | null
  sql: string
  chart: Partial<ChartSpec>
  position: number
  created_at: string
}

export interface DashboardDetail extends Dashboard {
  tiles: DashboardTile[]
}

export interface TileResult {
  tile_id: string
  ok: boolean
  result: ResultSet | null
  analysis: Analysis | null
  chart: ChartSpec | null
  validation: ValidationInfo | null
  cached: boolean
  error: string | null
}

export interface DashboardRefresh {
  dashboard_id: string
  refreshed_at: string
  tiles: TileResult[]
  duration_ms: number
}

/* ------------------------------ conversation & learning (phase 5) */

export interface ExplanationStep {
  order: number
  clause: string
  title: string
  detail: string
  sql: string
}

export interface Explanation {
  parsed: boolean
  summary: string
  steps: ExplanationStep[]
  tables: string[]
  aggregates: string[]
  row_limit: number | null
  is_aggregate: boolean
}

export interface UsedExample {
  question: string
  sql: string
  score: number
  source: 'correction' | 'history'
}

export interface GlossaryMatch {
  term: string
  definition: string
  sql_expression: string | null
}

export interface SemanticHit {
  question: string
  similarity: number
  embedder: string
}

export interface Suggestion {
  question: string
  reason: string
}

export interface Correction {
  id: string
  question: string
  original_sql: string | null
  corrected_sql: string
  note: string | null
  verified: boolean
  created_at: string
}

export interface GlossaryTerm {
  id: string
  term: string
  definition: string
  sql_expression: string | null
  created_at: string
  updated_at: string
}

export interface UsageTotals {
  queries: number
  executed: number
  rejected: number
  recovered_by_correction: number
  tokens: number
  estimated_cost_usd: number
  mean_latency_ms: number
}

export interface UsageByUser {
  user_id: string
  email: string
  queries: number
  tokens: number
  estimated_cost_usd: number
}

export interface UsageResponse {
  window_days: number
  scope: string
  totals: UsageTotals
  by_user: UsageByUser[]
  rates: { model: string; input_per_mtok: number; output_per_mtok: number }[]
  cost_note: string
}
