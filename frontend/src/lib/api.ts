import type { ApiDocumentation, PaginationConfig, RestBodyFormat, RestMethod, RunResponse, SavedQuery } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')

const AUTH_STORAGE_KEY = 'ossys-api-hub-basic-auth'
export const AUTH_REQUIRED_EVENT = 'ossys-api-hub:authorization-required'
let pendingAuthorization: Promise<string> | null = null
let resolveAuthorization: ((authorization: string) => void) | null = null
let rejectAuthorization: ((reason: Error) => void) | null = null

function requestAuthorization(): Promise<string> {
  if (pendingAuthorization) return pendingAuthorization
  pendingAuthorization = new Promise<string>((resolve, reject) => {
    resolveAuthorization = resolve
    rejectAuthorization = reject
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
  }).finally(() => {
    pendingAuthorization = null
    resolveAuthorization = null
    rejectAuthorization = null
  })
  return pendingAuthorization
}

export function provideAuthorization(username: string, password: string) {
  if (!resolveAuthorization) return
  const authorization = `Basic ${window.btoa(`${username}:${password}`)}`
  sessionStorage.setItem(AUTH_STORAGE_KEY, authorization)
  resolveAuthorization(authorization)
}

export function cancelAuthorization() {
  rejectAuthorization?.(new Error('Sign-in was cancelled'))
}

async function authorizedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = async (authorization?: string | null) => {
    const headers = new Headers(init?.headers)
    if (authorization) headers.set('Authorization', authorization)
    return fetch(input, { ...init, headers })
  }

  const savedAuthorization = sessionStorage.getItem(AUTH_STORAGE_KEY)
  let response = await request(savedAuthorization)
  if (response.status !== 401) return response

  sessionStorage.removeItem(AUTH_STORAGE_KEY)
  for (let attempt = 0; attempt < 2 && response.status === 401; attempt += 1) {
    const authorization = await requestAuthorization()
    response = await request(authorization)
    if (response.status === 401) sessionStorage.removeItem(AUTH_STORAGE_KEY)
  }
  return response
}

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
  const response = await authorizedFetch(`${API_BASE_URL}/api/run`, {
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
  const response = await authorizedFetch(`${API_BASE_URL}/api/rest/run`, {
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
  const response = await authorizedFetch(`${API_BASE_URL}/api/test-connection`, {
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
  const response = await authorizedFetch(`${API_BASE_URL}/api/rest/test-connection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<{ ok: boolean; status_code: number; message: string }>
}

export async function importOpenApiTemplates(url: string) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/openapi/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function getSavedQueries() {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function putSavedQueries(queries: SavedQuery[]) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(queries),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery[]>
}

export async function putSavedQuery(query: SavedQuery) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(query.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(query),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<SavedQuery>
}

export async function deleteSavedQuery(queryId: string) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(queryId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(await errorMessage(response))
}

export async function getQueryDocumentation(queryId: string) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(queryId)}/documentation`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<ApiDocumentation>
}

export async function refreshQueryDocumentation(queryId: string, input: {
  bearer_token?: string
  timeout_seconds: number
  verify_ssl: boolean
}) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-queries/${encodeURIComponent(queryId)}/documentation/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<ApiDocumentation>
}

export async function getSavedQueryGroups() {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-query-groups`)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<string[]>
}

export async function putSavedQueryGroups(groups: string[]) {
  const response = await authorizedFetch(`${API_BASE_URL}/api/saved-query-groups`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(groups),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<string[]>
}

export async function downloadExport(payload: Record<string, unknown>, filename: string) {
  const { downloadClientExport } = await import('./clientExport')
  await downloadClientExport(payload as unknown as import('./clientExport').ClientExportPayload, filename)
}
