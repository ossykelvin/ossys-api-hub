import type { SavedQuery } from '../types'

export const DEFAULT_SAVED_QUERY_GROUP = 'Employee'

export function parseJsonObject(text: string, name: string): Record<string, unknown> {
  if (!text.trim()) return {}
  const parsed: unknown = JSON.parse(text)
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${name} must be a JSON object.`)
  }
  return parsed as Record<string, unknown>
}

export function parseHeaders(text: string): Record<string, string> {
  const headers = parseJsonObject(text, 'Headers')
  const invalidHeader = Object.entries(headers).find(
    ([name, value]) => !name.trim() || typeof value !== 'string',
  )
  if (invalidHeader) {
    throw new Error('Header names must be non-empty and header values must be strings.')
  }
  return headers as Record<string, string>
}

export function flattenRecord(
  input: Record<string, unknown>,
  prefix = '',
): Record<string, unknown> {
  const output: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(input)) {
    const column = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(output, flattenRecord(value as Record<string, unknown>, column))
    } else {
      output[column] = Array.isArray(value) ? JSON.stringify(value) : value
    }
  }
  return output
}

export function loadSavedQueries(serialized: string | null): SavedQuery[] {
  if (!serialized) return []
  try {
    const value: unknown = JSON.parse(serialized)
    if (!Array.isArray(value)) return []
    return value.filter((item): item is SavedQuery => {
      if (!item || typeof item !== 'object') return false
      const candidate = item as Partial<SavedQuery>
      return typeof candidate.id === 'string'
        && typeof candidate.name === 'string'
        && typeof candidate.endpoint === 'string'
        && typeof candidate.query === 'string'
        && typeof candidate.variablesText === 'string'
        && typeof candidate.headersText === 'string'
        && typeof candidate.updatedAt === 'string'
        && !!candidate.pagination
        && typeof candidate.pagination === 'object'
    }).map((item) => ({
      ...item,
      group: typeof item.group === 'string' && item.group.trim()
        ? item.group.trim()
        : DEFAULT_SAVED_QUERY_GROUP,
    }))
  } catch {
    return []
  }
}

export function safeFileStem(value: string): string {
  return value.trim().replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '') || 'graphql-report'
}

export function uniqueReportFileStem(value: string, generatedAt = new Date()): string {
  const pad = (part: number, length = 2) => String(part).padStart(length, '0')
  const timestamp = [
    `${generatedAt.getFullYear()}-${pad(generatedAt.getMonth() + 1)}-${pad(generatedAt.getDate())}`,
    `${pad(generatedAt.getHours())}-${pad(generatedAt.getMinutes())}-${pad(generatedAt.getSeconds())}-${pad(generatedAt.getMilliseconds(), 3)}`,
  ].join('_')
  return `${safeFileStem(value)}_${timestamp}`
}
