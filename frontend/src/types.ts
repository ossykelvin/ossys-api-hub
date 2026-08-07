export type PaginationMode = 'none' | 'cursor' | 'page' | 'offset' | 'token'
export type ApiMode = 'graphql' | 'rest'
export type RestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'COPY'
export type RestBodyFormat = 'json' | 'form'

export interface PaginationConfig {
  mode: PaginationMode
  items_path: string
  record_path?: string | null
  page_size: number
  page_count: number | 'all'
  max_pages: number
  delay_ms: number
  page_variable: string
  page_size_variable: string
  starting_page: number
  total_pages_path?: string | null
  offset_variable: string
  limit_variable: string
  starting_offset: number
  cursor_variable: string
  cursor_page_size_variable: string
  has_next_page_path: string
  next_cursor_path: string
  token_variable: string
  next_token_path: string
}

export interface RunResponse {
  records: Record<string, unknown>[]
  pages: unknown[]
  page_count: number
  record_count: number
  duration_ms: number
  errors: Array<{ page: number; message: string; details?: unknown }>
  stopped_reason: string
}

export interface SavedQuery {
  id: string
  group?: string
  name: string
  endpoint: string
  query: string
  variablesText: string
  headersText: string
  pagination: PaginationConfig
  updatedAt: string
  apiMode?: ApiMode
  restMethod?: RestMethod
  restParamsText?: string
  restBodyText?: string
  restBodyFormat?: RestBodyFormat
  paginationLocation?: 'query' | 'body'
}

export interface ApiDocumentationParameter {
  name: string
  location?: string
  required?: boolean
  type?: string
  format?: string
  description?: string
  default?: unknown
  example?: unknown
  enum?: unknown[]
}

export interface ApiDocumentationResponse {
  status: string
  description?: string
  schema?: unknown
  example?: unknown
}

export interface ApiDocumentationInputField {
  name: string
  type?: string
  required?: boolean
  description?: string
  default?: unknown
  example?: unknown
  enumValues?: string[]
  inputFields?: ApiDocumentationInputField[]
}

export interface ApiDocumentationOutputField {
  name: string
  type?: string
  description?: string
  deprecated?: boolean
  deprecationReason?: string
  fields?: ApiDocumentationOutputField[]
}

export interface ApiDocumentation {
  queryId: string
  group: string
  status: string
  sourceType: string
  sourceUrl: string
  sourceLabel: string
  sourceVersion?: string
  fetchedAt: string
  summary: string
  description: string
  apiMode: ApiMode
  method: string
  endpoint: string
  tags?: string[]
  operationId?: string
  deprecated?: boolean
  parameters: ApiDocumentationParameter[]
  requestBody?: {
    contentType?: string
    required?: boolean
    description?: string
    schema?: unknown
    example?: unknown
  }
  responses: ApiDocumentationResponse[]
  pagination?: {
    mode?: string
    itemsPath?: string
    pageSize?: number
    maximumPages?: number
  }
  graphql?: {
    outputTreeVersion?: number
    rootField?: string
    arguments?: Array<ApiDocumentationInputField>
    returnType?: string
    fields?: ApiDocumentationOutputField[]
  }
}
