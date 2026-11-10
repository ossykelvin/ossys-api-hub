export function connectionKey(group: string, endpoint: string): string {
  try {
    const url = new URL(endpoint)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    return JSON.stringify([group, url.origin])
  } catch { return '' }
}

export function inheritedApiKey(group: string, endpoint: string, queries: Array<{ group?: string; endpoint: string; headersText: string }>): string {
  const scope = connectionKey(group, endpoint)
  if (!scope) return ''
  const keys = new Set<string>()
  for (const query of queries) {
    if (connectionKey(query.group?.trim() || 'Employee', query.endpoint) !== scope) continue
    try {
      const headers = JSON.parse(query.headersText)
      for (const [name, value] of Object.entries(headers)) {
        if (name.toLowerCase() === 'apikey' && typeof value === 'string' && value.trim()) keys.add(value.trim())
      }
    } catch { /* Invalid saved headers must not prevent opening another request. */ }
  }
  return keys.size === 1 ? [...keys][0] : ''
}

export function withApiKey(headers: Record<string, string>, apiKey: string): Record<string, string> {
  if (!apiKey || Object.keys(headers).some(name => name.toLowerCase() === 'apikey')) return headers
  return { ...headers, apikey: apiKey }
}
