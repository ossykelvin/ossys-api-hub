import type { ApiDocumentation, PaginationConfig, RestBodyFormat, RestMethod, RunResponse, SavedQuery } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')

function formatApiError(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const candidate = body as { detail?: unknown; message?: unknown }
  if (typeof candidate.detail === 'string') return candidate.detail
  if (typeof candidate.message === 'string') return candidate.message
  if (Array.isArray(candidate.detail)) {
    return candidate.detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item)
        const issue = item as { loc?: unknown[]; msg?: unknown }
        const location = issue.loc?.slice(1).join('.')
        return `${location ? `${location}: ` : ''}${String(issue.msg ?? 'Invalid value')}`
      })
      .join('; ')
  }
  return null
}

async function errorMessage(response: Response) {
  try {
    const body = await response.json()
    return formatApiError(body) || JSON.stringify(body)
  } catch {
    return `${response.status} ${response.statusText}`
  }
}

export async function runGraphQL(input: {
  endpoint: string
  bearer_token?: string
  headers: Record<string, string>
  query: string
  variables: Record<string, unknown>
  pagination: PaginationConfig
  timeout_seconds: number
  verify_ssl: boolean
}, signal?: AbortSignal): Promise<RunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function runRest(input: {
  endpoint: string
  method: RestMethod
  bearer_token?: string
  headers: Record<string, string>
  query_params: Record<string, unknown>
  body?: Record<string, unknown>
  body_format: RestBodyFormat
  pagination: PaginationConfig
  pagination_location: 'query' | 'body'
  timeout_seconds: number
  verify_ssl: boolean
}, signal?: AbortSignal): Promise<RunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/rest/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export async function testConnection(input: {
  endpoint: string
  bearer_token?: string
  headers: Record<string, string>
  timeout_seconds: number
  verify_ssl: boolean
}) {
  const response = await fetch(`${API_BASE_URL}/api/test-connection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<{ ok: boolean; status_code: number; message: string }>
}

export async function testRestConnection(input: {
  endpoint: string
  method: RestMethod
  bearer_token?: string
  headers: Record<string, string>
  query_params: Record<string, unknown>
  body?: Record<string, unknown>
  body_format: RestBodyFormat
  timeout_seconds: number
  verify_ssl: boolean
}) {
  const response = await fetch(`${API_BASE_URL}/api/rest/test-connection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<{ ok: boolean; status_code: number; message: string }>
}

export async function importOpenApiTemplates(url: string) {
  const response = await fetch(`${API_BASE_URL}/api/openapi/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function getSavedQueries() {
  const response = await fetch(`${API_BASE_URL}/api/saved-queries`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function putSavedQueries(queries: SavedQuery[]) {
  const response = await fetch(`${API_BASE_URL}/api/saved-queries`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(queries),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function getQueryDocumentation(queryId: string) {
  const response = await fetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(queryId)}/documentation`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<ApiDocumentation>
}

export async function refreshQueryDocumentation(queryId: string, input: {
  bearer_token?: string
  timeout_seconds: number
  verify_ssl: boolean
}) {
  const response = await fetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(queryId)}/documentation/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<ApiDocumentation>
}

export async function getSavedQueryGroups() {
  const response = await fetch(`${API_BASE_URL}/api/saved-query-groups`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<string[]>
}

export async function putSavedQueryGroups(groups: string[]) {
  const response = await fetch(`${API_BASE_URL}/api/saved-query-groups`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(groups),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<string[]>
}

export async function downloadExport(payload: Record<string, unknown>, filename: string) {
  const response = await fetch(`${API_BASE_URL}/api/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
