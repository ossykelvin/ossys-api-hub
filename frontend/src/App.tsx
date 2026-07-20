import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, Braces, CheckCircle2, ChevronDown, ChevronRight, CircleStop, Clock3, Copy, Database, Download,
  ExternalLink, FileJson, FileSpreadsheet, FolderOpen, KeyRound, Layers3, LoaderCircle, Moon, Play,
  Plus, RefreshCw, Save, Search, Settings2, Sun, Table2, Trash2, Wifi, XCircle,
} from 'lucide-react'
import './App.css'
import {
  deleteSavedQuery, downloadExport, getQueryDocumentation, getSavedQueries, getSavedQueryGroups, importOpenApiTemplates,
  putSavedQueries, putSavedQuery, putSavedQueryGroups,
  refreshQueryDocumentation, runGraphQL, runRest, testConnection, testRestConnection,
} from './lib/api'
import {
  DEFAULT_SAVED_QUERY_GROUP, flattenRecord, loadSavedQueries,
  parseHeaders, parseJsonObject, uniqueReportFileStem,
} from './lib/data'
import type { ApiDocumentation, ApiDocumentationInputField, ApiMode, PaginationConfig, PaginationMode, RestBodyFormat, RestMethod, RunResponse, SavedQuery } from './types'

const defaultQuery = `query GetRecords($first: Int!, $after: String) {
  records(first: $first, after: $after) {
    edges {
      node {
        id
        name
        status
        createdAt
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}`

const defaultVariables = '{\n  "first": 100,\n  "after": null\n}'

const defaultPagination: PaginationConfig = {
  mode: 'cursor',
  items_path: 'data.records.edges',
  record_path: 'node',
  page_size: 100,
  page_count: 1,
  max_pages: 500,
  delay_ms: 0,
  page_variable: 'page',
  page_size_variable: 'pageSize',
  starting_page: 1,
  total_pages_path: '',
  offset_variable: 'offset',
  limit_variable: 'limit',
  starting_offset: 0,
  cursor_variable: 'after',
  cursor_page_size_variable: 'first',
  has_next_page_path: 'data.records.pageInfo.hasNextPage',
  next_cursor_path: 'data.records.pageInfo.endCursor',
  token_variable: 'nextToken',
  next_token_path: 'data.records.nextToken',
}

const defaultRestPagination: PaginationConfig = {
  ...defaultPagination,
  mode: 'none',
  items_path: '',
  record_path: '',
  has_next_page_path: 'hasNextPage',
  next_cursor_path: 'nextCursor',
  next_token_path: 'nextToken',
}

const SAVED_KEY = 'graphql-hub.saved-queries.v1'
const THEME_KEY = 'graphql-hub.theme'
const GROUP_TOKENS_KEY = 'graphql-hub.group-tokens.v1'
const SELECTED_QUERY_KEY = 'graphql-hub.selected-query.v1'
const ACTIVE_GROUP_KEY = 'graphql-hub.active-group.v1'
const ADD_GROUP_VALUE = '__add_group__'
const ALL_GROUPS_VALUE = 'ALL'
const DEFAULT_OPENAPI_URL = 'https://csat5.resourcescheduler.net/RSMCP/swagger/docs/v1'

type ResultTab = 'json' | 'table' | 'errors'

type SavedQueryContextMenu = {
  queryId: string
  x: number
  y: number
}

function findAccessToken(pages: unknown[]): string | null {
  for (const page of pages) {
    if (!page || typeof page !== 'object' || Array.isArray(page)) continue
    const response = page as Record<string, unknown>
    const candidate = response.access_token ?? response.accessToken ?? response.token
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return null
}

function normalizedGroup(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : DEFAULT_SAVED_QUERY_GROUP
}

function loadGroupTokens(): Record<string, string> {
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(GROUP_TOKENS_KEY) || '{}')
    if (!stored || Array.isArray(stored) || typeof stored !== 'object') return {}
    return Object.fromEntries(
      Object.entries(stored).filter(([group, value]) => group.trim() && typeof value === 'string'),
    ) as Record<string, string>
  } catch {
    return {}
  }
}

function cacheSavedQueries(queries: SavedQuery[]) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(queries))
  } catch {
    localStorage.removeItem(SAVED_KEY)
  }
}

function documentationValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'Not specified'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function DocumentationInputFields({ fields }: { fields: ApiDocumentationInputField[] }) {
  if (fields.length === 0) return null
  return <div className="documentation-input-fields">
    {fields.map((field) => {
      const nestedFields = field.inputFields || []
      const content = <>
        <span className="documentation-input-name"><code>{field.name}</code>{field.required && <em>Required</em>}</span>
        <code>{field.type || 'Unknown'}</code>
        <span>{field.description || 'No description supplied.'}</span>
      </>
      return nestedFields.length > 0
        ? <details key={field.name}><summary>{content}</summary><div className="documentation-input-detail">{field.enumValues && field.enumValues.length > 0 && <p><strong>Allowed values:</strong> {field.enumValues.join(', ')}</p>}<DocumentationInputFields fields={nestedFields} /></div></details>
        : <div className="documentation-input-row" key={field.name}>{content}</div>
    })}
  </div>
}

function App() {
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem(THEME_KEY) !== 'light')
  const [apiMode, setApiMode] = useState<ApiMode>('graphql')
  const [endpoint, setEndpoint] = useState('')
  const [queryGroup, setQueryGroup] = useState(() => sessionStorage.getItem(ACTIVE_GROUP_KEY) || DEFAULT_SAVED_QUERY_GROUP)
  const [queryGroups, setQueryGroups] = useState<string[]>([ALL_GROUPS_VALUE, DEFAULT_SAVED_QUERY_GROUP])
  const [queryGroupsReady, setQueryGroupsReady] = useState(false)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set())
  const [addingGroup, setAddingGroup] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [groupTokens, setGroupTokens] = useState<Record<string, string>>(loadGroupTokens)
  const [token, setToken] = useState(() => {
    const activeGroup = sessionStorage.getItem(ACTIVE_GROUP_KEY) || DEFAULT_SAVED_QUERY_GROUP
    return loadGroupTokens()[activeGroup] ?? ''
  })
  const [showToken, setShowToken] = useState(false)
  const [queryName, setQueryName] = useState('Untitled report')
  const [query, setQuery] = useState(defaultQuery)
  const [variablesText, setVariablesText] = useState(defaultVariables)
  const [headersText, setHeadersText] = useState('{}')
  const [restMethod, setRestMethod] = useState<RestMethod>('GET')
  const [restParamsText, setRestParamsText] = useState('{}')
  const [restBodyText, setRestBodyText] = useState('{}')
  const [restBodyFormat, setRestBodyFormat] = useState<RestBodyFormat>('json')
  const [paginationLocation, setPaginationLocation] = useState<'query' | 'body'>('query')
  const [pagination, setPagination] = useState<PaginationConfig>({ ...defaultPagination })
  const [verifySsl, setVerifySsl] = useState(true)
  const [timeoutSeconds, setTimeoutSeconds] = useState(60)
  const [result, setResult] = useState<RunResponse | null>(null)
  const [resultTab, setResultTab] = useState<ResultTab>('json')
  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState('Ready')
  const [error, setError] = useState('')
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'testing' | 'ok' | 'failed'>('idle')
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>(() => loadSavedQueries(localStorage.getItem(SAVED_KEY)))
  const [savedQueriesReady, setSavedQueriesReady] = useState(false)
  const [selectedQueryId, setSelectedQueryId] = useState<string | null>(() => sessionStorage.getItem(SELECTED_QUERY_KEY))
  const [sidebarSearch, setSidebarSearch] = useState('')
  const [savedQueryContextMenu, setSavedQueryContextMenu] = useState<SavedQueryContextMenu | null>(null)
  const [documentationOpen, setDocumentationOpen] = useState(false)
  const [documentationQueryId, setDocumentationQueryId] = useState<string | null>(null)
  const [documentation, setDocumentation] = useState<ApiDocumentation | null>(null)
  const [documentationLoading, setDocumentationLoading] = useState(false)
  const [documentationRefreshing, setDocumentationRefreshing] = useState(false)
  const [documentationError, setDocumentationError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const restoredSelectionRef = useRef(false)

  const loadSaved = useCallback((item: SavedQuery) => {
    setSelectedQueryId(item.id)
    const savedApiMode = item.apiMode ?? 'graphql'
    const group = normalizedGroup(item.group)
    setApiMode(savedApiMode)
    setQueryGroup(group)
    setToken(groupTokens[group] ?? '')
    setQueryName(item.name)
    setEndpoint(item.endpoint)
    setQuery(item.query)
    setVariablesText(item.variablesText)
    setHeadersText(item.headersText)
    setRestMethod(item.restMethod ?? 'GET')
    setRestParamsText(item.restParamsText ?? '{}')
    setRestBodyText(item.restBodyText ?? '{}')
    setRestBodyFormat(item.restBodyFormat ?? 'json')
    setPaginationLocation(item.paginationLocation ?? 'query')
    setPagination({ ...(savedApiMode === 'graphql' ? defaultPagination : defaultRestPagination), ...item.pagination })
    setStatus(`Loaded ${item.name}`)
  }, [groupTokens])

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light'
    localStorage.setItem(THEME_KEY, darkMode ? 'dark' : 'light')
  }, [darkMode])

  useEffect(() => sessionStorage.setItem(GROUP_TOKENS_KEY, JSON.stringify(groupTokens)), [groupTokens])

  useEffect(() => sessionStorage.setItem(ACTIVE_GROUP_KEY, normalizedGroup(queryGroup)), [queryGroup])

  useEffect(() => {
    if (selectedQueryId) sessionStorage.setItem(SELECTED_QUERY_KEY, selectedQueryId)
    else sessionStorage.removeItem(SELECTED_QUERY_KEY)
  }, [selectedQueryId])

  useEffect(() => {
    if (!savedQueryContextMenu) return
    const closeMenu = () => setSavedQueryContextMenu(null)
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
    }
    document.addEventListener('click', closeMenu)
    document.addEventListener('keydown', closeOnEscape)
    window.addEventListener('blur', closeMenu)
    window.addEventListener('resize', closeMenu)
    window.addEventListener('scroll', closeMenu, true)
    return () => {
      document.removeEventListener('click', closeMenu)
      document.removeEventListener('keydown', closeOnEscape)
      window.removeEventListener('blur', closeMenu)
      window.removeEventListener('resize', closeMenu)
      window.removeEventListener('scroll', closeMenu, true)
    }
  }, [savedQueryContextMenu])

  useEffect(() => {
    if (!documentationOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDocumentationOpen(false)
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [documentationOpen])

  useEffect(() => {
    let active = true
    getSavedQueries()
      .then((remoteQueries) => {
        if (!active) return
        setSavedQueries(remoteQueries)
        cacheSavedQueries(remoteQueries)
        setSavedQueriesReady(true)
      })
      .catch((caught: Error) => {
        if (!active) return
        setError(`Saved queries could not be loaded: ${caught.message}`)
        setSavedQueriesReady(true)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    getSavedQueryGroups()
      .then((remoteGroups) => {
        if (!active) return
        setQueryGroups(Array.from(new Set([ALL_GROUPS_VALUE, DEFAULT_SAVED_QUERY_GROUP, ...remoteGroups])))
        setQueryGroupsReady(true)
      })
      .catch((caught: Error) => {
        if (!active) return
        setError(`Saved query groups could not be loaded: ${caught.message}`)
        setQueryGroupsReady(true)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!savedQueriesReady) return
    cacheSavedQueries(savedQueries)
  }, [savedQueries, savedQueriesReady])

  useEffect(() => {
    if (!savedQueriesReady || restoredSelectionRef.current) return
    restoredSelectionRef.current = true
    if (!selectedQueryId) return
    const selectedQuery = savedQueries.find((item) => item.id === selectedQueryId)
    if (selectedQuery) loadSaved(selectedQuery)
    else setSelectedQueryId(null)
  }, [loadSaved, savedQueries, savedQueriesReady, selectedQueryId])

  const rows = useMemo(() => (result?.records || []).map((row) => flattenRecord(row)), [result])
  const columns = useMemo(() => {
    const values = new Set<string>()
    rows.slice(0, 200).forEach((row) => Object.keys(row).forEach((key) => values.add(key)))
    return Array.from(values)
  }, [rows])
  const visibleSaved = useMemo(() => {
    const searchTerm = sidebarSearch.trim().toLowerCase()
    if (!searchTerm) return savedQueries

    return savedQueries.filter((item) =>
      item.name.toLowerCase().includes(searchTerm)
      || item.endpoint.toLowerCase().includes(searchTerm),
    )
  }, [savedQueries, sidebarSearch])
  const savedGroups = useMemo(
    () => Array.from(new Set([
      ALL_GROUPS_VALUE,
      DEFAULT_SAVED_QUERY_GROUP,
      ...queryGroups,
      normalizedGroup(queryGroup),
      ...savedQueries.map((item) => normalizedGroup(item.group)),
    ])).sort((left, right) => left.localeCompare(right)),
    [queryGroup, queryGroups, savedQueries],
  )
  useEffect(() => {
    if (!queryGroupsReady || !savedQueriesReady) return
    const current = [...queryGroups].sort((left, right) => left.localeCompare(right))
    if (JSON.stringify(current) === JSON.stringify(savedGroups)) return
    setQueryGroups(savedGroups)
    putSavedQueryGroups(savedGroups).catch((caught: Error) => {
      setError(`Saved query groups could not be persisted: ${caught.message}`)
    })
  }, [queryGroups, queryGroupsReady, savedGroups, savedQueriesReady])
  const groupedSaved = useMemo(() => {
    const navigableGroups = savedGroups.filter((group) => group !== ALL_GROUPS_VALUE)
    const groups = new Map<string, SavedQuery[]>(sidebarSearch ? [] : navigableGroups.map((group) => [group, []]))
    for (const item of visibleSaved) {
      const group = normalizedGroup(item.group)
      if (group === ALL_GROUPS_VALUE) continue
      groups.set(group, [...(groups.get(group) ?? []), item])
    }
    return Array.from(groups.entries()).sort(([left], [right]) => left.localeCompare(right))
  }, [savedGroups, sidebarSearch, visibleSaved])
  const sidebarGroups = useMemo(
    () => normalizedGroup(queryGroup) === ALL_GROUPS_VALUE
      ? groupedSaved
      : groupedSaved.filter(([group]) => group === normalizedGroup(queryGroup)),
    [groupedSaved, queryGroup],
  )

  function updatePagination<K extends keyof PaginationConfig>(key: K, value: PaginationConfig[K]) {
    setPagination((current) => ({ ...current, [key]: value }))
  }

  function setTokenForGroup(group: string, value: string) {
    const normalized = normalizedGroup(group)
    setGroupTokens((current) => {
      if (value) return { ...current, [normalized]: value }
      const next = { ...current }
      delete next[normalized]
      return next
    })
    setToken(value)
  }

  function handleGroupChange(value: string) {
    const group = normalizedGroup(value)
    setExpandedGroups(new Set())
    const selectedQuery = selectedQueryId
      ? savedQueries.find((item) => item.id === selectedQueryId)
      : undefined
    const nextQuery = selectedQuery && normalizedGroup(selectedQuery.group) === group
      ? selectedQuery
      : savedQueries.find((item) => normalizedGroup(item.group) === group)
    if (nextQuery) {
      loadSaved(nextQuery)
      return
    }
    setQueryGroup(group)
    setToken(groupTokens[group] ?? '')
    setSelectedQueryId(null)
    setQueryName('Untitled report')
    setEndpoint('')
    setResult(null)
    setConnectionStatus('idle')
    setStatus(`Group ${group} selected; create or save a query to add it`)
  }

  function toggleGroup(group: string) {
    setExpandedGroups((current) => {
      const next = new Set(current)
      if (next.has(group)) next.delete(group)
      else next.add(group)
      return next
    })
  }

  function openSavedQueryContextMenu(event: React.MouseEvent, queryId: string) {
    event.preventDefault()
    event.stopPropagation()
    const menuWidth = 210
    const menuHeight = Math.min(320, 58 + Math.max(1, savedGroups.length - 2) * 38)
    setSavedQueryContextMenu({
      queryId,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
    })
  }

  async function moveSavedQuery(queryId: string, destinationGroup: string) {
    const group = normalizedGroup(destinationGroup)
    const savedQuery = savedQueries.find((item) => item.id === queryId)
    if (!savedQuery || group === ALL_GROUPS_VALUE || normalizedGroup(savedQuery.group) === group) {
      setSavedQueryContextMenu(null)
      return
    }
    const movedQuery = { ...savedQuery, group, updatedAt: new Date().toISOString() }
    try {
      await putSavedQuery(movedQuery)
      setSavedQueries((current) => current.map((item) => item.id === queryId ? movedQuery : item))
    } catch (caught) {
      setError(`Saved query could not be moved: ${(caught as Error).message}`)
      setSavedQueryContextMenu(null)
      return
    }
    if (selectedQueryId === queryId) {
      setQueryGroup(group)
      setToken(groupTokens[group] ?? '')
      setExpandedGroups(new Set([group]))
    }
    setSavedQueryContextMenu(null)
    setStatus(`${savedQuery.name} moved to ${group}`)
  }

  async function openDocumentation(queryId?: string | null) {
    const id = queryId ?? selectedQueryId
    if (!id) {
      setError('Select a saved query before opening documentation')
      return
    }
    setSavedQueryContextMenu(null)
    setDocumentationOpen(true)
    setDocumentationQueryId(id)
    setDocumentation(null)
    setDocumentationError('')
    setDocumentationLoading(true)
    try {
      setDocumentation(await getQueryDocumentation(id))
    } catch (caught) {
      setDocumentationError((caught as Error).message)
    } finally {
      setDocumentationLoading(false)
    }
  }

  async function refreshDocumentation() {
    if (!documentationQueryId) return
    const savedQuery = savedQueries.find((item) => item.id === documentationQueryId)
    if (!savedQuery) return
    const group = normalizedGroup(savedQuery.group)
    setDocumentationError('')
    setDocumentationRefreshing(true)
    try {
      const refreshed = await refreshQueryDocumentation(documentationQueryId, {
        bearer_token: groupTokens[group] || undefined,
        timeout_seconds: Math.min(timeoutSeconds, 120),
        verify_ssl: verifySsl,
      })
      setDocumentation(refreshed)
      setStatus(`Documentation refreshed for ${savedQuery.name}`)
    } catch (caught) {
      setDocumentationError((caught as Error).message)
    } finally {
      setDocumentationRefreshing(false)
    }
  }

  async function copyArgumentExample(argument: ApiDocumentationInputField) {
    try {
      await navigator.clipboard.writeText(documentationValue({ [argument.name]: argument.example }))
      setStatus(`Example copied for ${argument.name}`)
    } catch {
      setDocumentationError('The argument example could not be copied to the clipboard')
    }
  }

  async function copyQueryToClipboard() {
    const content = apiMode === 'graphql'
      ? query
      : [
          `${restMethod} ${endpoint}`,
          `Query parameters:\n${restParamsText.trim() || '{}'}`,
          ...(restMethod !== 'GET' ? [`Request body:\n${restBodyText.trim() || '{}'}`] : []),
          `Headers:\n${headersText.trim() || '{}'}`,
        ].join('\n\n')
    try {
      await navigator.clipboard.writeText(content)
      setStatus(`${apiMode === 'graphql' ? 'Query' : 'REST request'} copied to clipboard`)
    } catch {
      setError(`${apiMode === 'graphql' ? 'Query' : 'REST request'} could not be copied to the clipboard`)
    }
  }

  async function copyResultsToClipboard() {
    if (!result) return
    let content: string
    if (resultTab === 'table') {
      const cleanCell = (value: unknown) => value == null ? '' : String(value).replace(/[\t\r\n]+/g, ' ')
      content = [
        columns.join('\t'),
        ...rows.map((row) => columns.map((column) => cleanCell(row[column])).join('\t')),
      ].join('\n')
    } else if (resultTab === 'errors') {
      content = JSON.stringify(result.errors, null, 2)
    } else {
      content = JSON.stringify(result.pages.length === 1 ? result.pages[0] : result.pages, null, 2)
    }
    try {
      await navigator.clipboard.writeText(content)
      setStatus(`${resultTab === 'table' ? 'Table' : resultTab === 'errors' ? 'Errors' : 'JSON results'} copied to clipboard`)
    } catch {
      setError('Results could not be copied to the clipboard')
    }
  }

  function handleCreateGroup() {
    const enteredName = newGroupName.trim()
    if (!enteredName) return
    const name = savedGroups.find((group) => group.toLowerCase() === enteredName.toLowerCase()) ?? enteredName
    const nextGroups = Array.from(new Set([...savedGroups, name])).sort((left, right) => left.localeCompare(right))
    handleGroupChange(name)
    setQueryGroups(nextGroups)
    setAddingGroup(false)
    setNewGroupName('')
    setStatus(`Group ${name} saved`)
    putSavedQueryGroups(nextGroups)
      .then(setQueryGroups)
      .catch((caught: Error) => {
        setError(`Group ${name} could not be saved: ${caught.message}`)
      })
  }

  function handleNewQuery() {
    setSelectedQueryId(null)
    setQueryName('Untitled report')
    setQuery(defaultQuery)
    setVariablesText(defaultVariables)
    setHeadersText('{}')
    setRestMethod('GET')
    setRestParamsText('{}')
    setRestBodyText('{}')
    setRestBodyFormat('json')
    setPaginationLocation('query')
    setPagination({ ...(apiMode === 'graphql' ? defaultPagination : defaultRestPagination) })
    setResult(null)
    setError('')
    setStatus('New query ready')
  }

  function buildCommonRequest() {
    if (!endpoint.trim()) throw new Error(`Enter a ${apiMode === 'graphql' ? 'GraphQL' : 'REST'} endpoint URL.`)
    return {
      endpoint: endpoint.trim(),
      bearer_token: token.trim() || undefined,
      headers: parseHeaders(headersText),
      timeout_seconds: timeoutSeconds,
      verify_ssl: verifySsl,
    }
  }

  function buildGraphQLRequest() {
    return {
      ...buildCommonRequest(),
      query,
      variables: parseJsonObject(variablesText, 'Variables'),
      pagination,
    }
  }

  function buildRestRequest() {
    return {
      ...buildCommonRequest(),
      method: restMethod,
      query_params: parseJsonObject(restParamsText, 'Query parameters'),
      body: restMethod !== 'GET' ? parseJsonObject(restBodyText, 'Request body') : undefined,
      body_format: restBodyFormat,
      pagination,
      pagination_location: paginationLocation,
    }
  }

  function handleApiModeChange(mode: ApiMode) {
    setApiMode(mode)
    setPagination({ ...(mode === 'graphql' ? defaultPagination : defaultRestPagination) })
    setConnectionStatus('idle')
    setResult(null)
    setError('')
    setStatus(`${mode === 'graphql' ? 'GraphQL' : 'REST'} request ready`)
  }

  async function handleImportOpenApi() {
    setError('')
    setStatus('Importing API templates…')
    try {
      const group = normalizedGroup(queryGroup)
      const templates = (await importOpenApiTemplates(DEFAULT_OPENAPI_URL)).map((item) => ({ ...item, group }))
      setSavedQueries(await putSavedQueries(templates))
      setStatus(`${templates.length} API templates imported`)
    } catch (caught) {
      setError((caught as Error).message)
      setStatus('API template import failed')
    }
  }

  async function handleRun() {
    setError('')
    try {
      const controller = new AbortController()
      abortRef.current = controller
      setRunning(true)
      setStatus(pagination.page_count === 'all' ? 'Collecting all pages…' : 'Executing report…')
      const response = apiMode === 'graphql'
        ? await runGraphQL(buildGraphQLRequest(), controller.signal)
        : await runRest(buildRestRequest(), controller.signal)
      const capturedToken = apiMode === 'rest' ? findAccessToken(response.pages) : null
      if (capturedToken) setTokenForGroup(queryGroup, capturedToken)
      setResult(response)
      setResultTab(response.errors.length > 0 ? 'errors' : 'json')
      setStatus(
        `${response.record_count.toLocaleString()} records from ${response.page_count} page${response.page_count === 1 ? '' : 's'}`
        + (capturedToken ? ' · session token captured' : ''),
      )
    } catch (caught) {
      if ((caught as Error).name === 'AbortError') setStatus('Execution cancelled')
      else { setError((caught as Error).message); setStatus('Execution failed') }
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  async function handleTest() {
    setError('')
    try {
      const commonRequest = buildCommonRequest()
      setConnectionStatus('testing')
      const response = apiMode === 'graphql'
        ? await testConnection({
            ...commonRequest,
            timeout_seconds: Math.min(timeoutSeconds, 120),
          })
        : await testRestConnection({
            ...commonRequest,
            method: restMethod,
            query_params: parseJsonObject(restParamsText, 'Query parameters'),
            body: restMethod !== 'GET' ? parseJsonObject(restBodyText, 'Request body') : undefined,
            body_format: restBodyFormat,
            timeout_seconds: Math.min(timeoutSeconds, 120),
          })
      setConnectionStatus(response.ok ? 'ok' : 'failed')
      setStatus(response.message)
    } catch (caught) {
      setConnectionStatus('failed')
      setError((caught as Error).message)
    }
  }

  async function handleSave() {
    const id = selectedQueryId ?? crypto.randomUUID()
    const item: SavedQuery = {
      id,
      group: normalizedGroup(queryGroup),
      name: queryName.trim() || 'Untitled report',
      endpoint, query, variablesText, headersText, pagination,
      updatedAt: new Date().toISOString(),
      apiMode,
      restMethod,
      restParamsText,
      restBodyText,
      restBodyFormat,
      paginationLocation,
    }
    setStatus('Saving query…')
    setError('')
    try {
      await putSavedQuery(item)
      setSavedQueries((current) => [item, ...current.filter((saved) => saved.id !== id)])
      setQueryGroup(normalizedGroup(item.group))
      setSelectedQueryId(id)
      setStatus('Query saved')
    } catch (caught) {
      setError(`Query could not be saved: ${(caught as Error).message}`)
      setStatus('Save failed')
    }
  }

  async function handleDeleteSavedQuery(item: SavedQuery) {
    try {
      await deleteSavedQuery(item.id)
      setSavedQueries((current) => current.filter((saved) => saved.id !== item.id))
      if (selectedQueryId === item.id) setSelectedQueryId(null)
      setStatus(`${item.name} deleted`)
    } catch (caught) {
      setError(`Saved query could not be deleted: ${(caught as Error).message}`)
    }
  }

  async function handleExport(format: 'xlsx' | 'csv' | 'json') {
    if (!result) return
    setError('')
    try {
      setStatus(`Preparing ${format.toUpperCase()}…`)
      const baseName = uniqueReportFileStem(queryName)
      await downloadExport({
        format,
        records: result.records,
        query: apiMode === 'graphql' ? query : `${restMethod} ${endpoint}`,
        variables: apiMode === 'graphql'
          ? parseJsonObject(variablesText, 'Variables')
          : {
              queryParameters: parseJsonObject(restParamsText, 'Query parameters'),
              body: restMethod !== 'GET' ? parseJsonObject(restBodyText, 'Request body') : undefined,
            },
        endpoint,
        run_summary: {
          'Pages retrieved': result.page_count,
          'Records retrieved': result.record_count,
          'Duration (ms)': result.duration_ms,
          'Stopped because': result.stopped_reason,
        },
        errors: result.errors,
        filename: baseName,
      }, `${baseName}.${format}`)
      setStatus(`${format.toUpperCase()} downloaded`)
    } catch (caught) {
      setError((caught as Error).message)
      setStatus('Export failed')
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Braces size={22} /></div>
          <div><strong>Ossy's API Hub</strong><span>Report workspace</span></div>
        </div>
        <button className="new-query" onClick={handleNewQuery}><Plus size={17} /> New query</button>
        <button className="import-queries" onClick={handleImportOpenApi}><Download size={15} /> Import API catalogue</button>
        <div className="sidebar-section">
          <div className="section-label"><FolderOpen size={14} /> Saved queries</div>
          <label className="sidebar-search"><Search size={14} /><input value={sidebarSearch} onChange={(e) => setSidebarSearch(e.target.value)} placeholder="Search name or endpoint" /></label>
          <div className="saved-list">
            {visibleSaved.length === 0 && <div className="empty-small">No saved queries yet.</div>}
            {sidebarGroups.map(([group, items]) => {
              const expanded = expandedGroups.has(group)
              return <section className="saved-group" key={group}>
                <button
                  aria-expanded={expanded}
                  className={`saved-group-title ${normalizedGroup(queryGroup) === group ? 'active' : ''}`}
                  onClick={() => toggleGroup(group)}
                >
                  <span className="saved-group-name">{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{group}</span>
                  <small>{items.length}</small>
                </button>
                {expanded && <div className="saved-group-items">
                  {items.length === 0 && <div className="saved-group-empty">No queries in this group</div>}
                  {items.map((item) => (
                    <div
                      className={`saved-item ${selectedQueryId === item.id ? 'active' : ''}`}
                      key={item.id}
                      onContextMenu={(event) => openSavedQueryContextMenu(event, item.id)}
                    >
                      <button title={`${item.name} — right-click to move`} onClick={() => loadSaved(item)}><span>{item.name}</span><small>{new Date(item.updatedAt).toLocaleDateString()}</small></button>
                      <button
                        aria-label={`Delete ${item.name}`}
                        className="delete-button"
                        onClick={() => void handleDeleteSavedQuery(item)}
                      ><Trash2 size={14} /></button>
                    </div>
                  ))}
                </div>}
              </section>
            })}
          </div>
        </div>
        <div className="sidebar-footer">
          <div className="ai-state"><span className="status-dot" /> AI fallback disabled</div>
          <button className="icon-button" onClick={() => setDarkMode((value) => !value)}>{darkMode ? <Sun size={17} /> : <Moon size={17} />}</button>
        </div>
      </aside>

      {savedQueryContextMenu && (() => {
        const savedQuery = savedQueries.find((item) => item.id === savedQueryContextMenu.queryId)
        if (!savedQuery) return null
        const currentGroup = normalizedGroup(savedQuery.group)
        const destinationGroups = savedGroups.filter((group) => group !== ALL_GROUPS_VALUE && group !== currentGroup)
        return <div
          className="saved-query-context-menu"
          role="menu"
          aria-label={`Move ${savedQuery.name} to another group`}
          style={{ left: savedQueryContextMenu.x, top: savedQueryContextMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="saved-query-context-heading">
            <span>Move to group</span>
            <small title={savedQuery.name}>{savedQuery.name}</small>
          </div>
          <div className="saved-query-context-options">
            <button className="saved-query-documentation-action" role="menuitem" onClick={() => openDocumentation(savedQuery.id)}>
              <BookOpen size={14} /><span>View documentation</span>
            </button>
            {destinationGroups.length > 0 && <div className="saved-query-context-divider" />}
            {destinationGroups.length === 0
              ? <div className="saved-query-context-empty">No other groups available</div>
              : destinationGroups.map((group) => <button
                key={group}
                role="menuitem"
                onClick={() => void moveSavedQuery(savedQuery.id, group)}
              ><FolderOpen size={14} /><span>{group}</span></button>)}
          </div>
        </div>
      })()}

      <main className="workspace">
        <header className="topbar">
          <div><h1>{queryName}</h1><p>Build, paginate and export GraphQL or REST API reports locally.</p></div>
          <div className="top-actions">
            <label className="group-control">
              <span>Group</span>
              {addingGroup ? <>
                <input
                  autoFocus
                  aria-label="New group name"
                  value={newGroupName}
                  onChange={(event) => setNewGroupName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') { event.preventDefault(); handleCreateGroup() }
                    if (event.key === 'Escape') { setAddingGroup(false); setNewGroupName('') }
                  }}
                  placeholder="Group name"
                />
                <button type="button" aria-label="Create group" onClick={handleCreateGroup}><CheckCircle2 size={15} /></button>
                <button type="button" aria-label="Cancel new group" onClick={() => { setAddingGroup(false); setNewGroupName('') }}><XCircle size={15} /></button>
              </> : <select value={normalizedGroup(queryGroup)} onChange={(event) => {
                if (event.target.value === ADD_GROUP_VALUE) {
                  setAddingGroup(true)
                  setNewGroupName('')
                } else handleGroupChange(event.target.value)
              }}>
                {savedGroups.map((group) => <option value={group} key={group}>{group}</option>)}
                <option value={ADD_GROUP_VALUE}>+ Add new group…</option>
              </select>}
            </label>
            <button className="secondary-button documentation-button" onClick={() => openDocumentation()} disabled={!selectedQueryId}><BookOpen size={16} /> Documentation</button>
            <label className="api-mode-control">
              <span>API type</span>
              <select value={apiMode} onChange={(event) => handleApiModeChange(event.target.value as ApiMode)}>
                <option value="graphql">GraphQL</option>
                <option value="rest">REST</option>
              </select>
            </label>
            <button className="secondary-button" onClick={handleSave}><Save size={16} /> Save</button>
            {running
              ? <button className="danger-button" onClick={() => abortRef.current?.abort()}><CircleStop size={16} /> Cancel</button>
              : <button className="primary-button" onClick={handleRun}><Play size={16} /> Run report</button>}
          </div>
        </header>

        {error && <div className="error-banner"><XCircle size={17} /><span>{error}</span><button onClick={() => setError('')}>×</button></div>}

        <section className="connection-card card">
          <div className="card-title"><div><Wifi size={18} /><span>Connection</span></div><span className={`connection-chip ${connectionStatus}`}>{connectionStatus === 'ok' ? 'Connected' : connectionStatus === 'testing' ? 'Testing…' : connectionStatus === 'failed' ? 'Failed' : 'Not tested'}</span></div>
          <div className="connection-grid">
            <label className="field wide"><span>Endpoint URL</span><div className="input-with-icon"><Database size={16} /><input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder={apiMode === 'graphql' ? 'https://api.example.com/graphql' : 'https://api.example.com/v1/items'} /></div></label>
            <label className="field"><span>Bearer token {token && <em className="memory-badge">{normalizedGroup(queryGroup)} session</em>}</span><div className="input-with-icon"><KeyRound size={16} /><input type={showToken ? 'text' : 'password'} value={token} onChange={(e) => setTokenForGroup(queryGroup, e.target.value)} placeholder="Captured for this group or enter manually" /><button onClick={() => setShowToken((value) => !value)} type="button">{showToken ? 'Hide' : 'Show'}</button></div></label>
            <button className="secondary-button test-button" onClick={handleTest} disabled={connectionStatus === 'testing'}>{connectionStatus === 'testing' ? <LoaderCircle className="spin" size={16} /> : <Wifi size={16} />} Test</button>
          </div>
        </section>

        <section className="editor-grid">
          <div className="editor-card card">
            <div className="card-title"><div><Braces size={18} /><span>{apiMode === 'graphql' ? 'GraphQL query' : 'REST request'}</span></div><div className="card-title-actions"><button type="button" onClick={copyQueryToClipboard} disabled={apiMode === 'graphql' ? !query.trim() : !endpoint.trim()} title={`Copy ${apiMode === 'graphql' ? 'query' : 'REST request'}`}><Copy size={14} /> Copy</button><input className="query-name-input" value={queryName} onChange={(e) => setQueryName(e.target.value)} /></div></div>
            {apiMode === 'graphql' ? <>
              <textarea aria-label="GraphQL query" className="code-editor query-editor" value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} />
              <div className="split-editors">
                <label><span>Variables</span><textarea className="code-editor small-editor" value={variablesText} onChange={(e) => setVariablesText(e.target.value)} spellCheck={false} /></label>
                <label><span>Custom headers</span><textarea className="code-editor small-editor" value={headersText} onChange={(e) => setHeadersText(e.target.value)} spellCheck={false} /></label>
              </div>
            </> : <>
              <div className="rest-method-bar">
                <label className="field"><span>HTTP method</span><select value={restMethod} onChange={(event) => {
                  const method = event.target.value as RestMethod
                  setRestMethod(method)
                  if (method === 'GET') setPaginationLocation('query')
                }}><option value="GET">GET</option><option value="POST">POST</option><option value="PUT">PUT</option><option value="PATCH">PATCH</option><option value="DELETE">DELETE</option><option value="COPY">COPY</option></select></label>
                {restMethod !== 'GET' && <label className="field"><span>Body format</span><select value={restBodyFormat} onChange={(event) => setRestBodyFormat(event.target.value as RestBodyFormat)}><option value="json">JSON</option><option value="form">Form URL encoded</option></select></label>}
                <p>REST responses must be JSON. Leave the items path blank when the response is an array.</p>
              </div>
              <div className="split-editors">
                <label><span>Query parameters (JSON)</span><textarea className="code-editor rest-editor" value={restParamsText} onChange={(e) => setRestParamsText(e.target.value)} spellCheck={false} /></label>
                <label><span>{restMethod !== 'GET' ? 'Request body (JSON)' : 'Custom headers'}</span><textarea className="code-editor rest-editor" value={restMethod !== 'GET' ? restBodyText : headersText} onChange={(e) => restMethod !== 'GET' ? setRestBodyText(e.target.value) : setHeadersText(e.target.value)} spellCheck={false} /></label>
              </div>
              {restMethod !== 'GET' && <label className="rest-full-editor"><span>Custom headers</span><textarea className="code-editor small-editor" value={headersText} onChange={(e) => setHeadersText(e.target.value)} spellCheck={false} /></label>}
            </>}
          </div>

          <div className="settings-card card">
            <div className="card-title"><div><Settings2 size={18} /><span>Pagination</span></div></div>
            <label className="field"><span>Strategy</span><select value={pagination.mode} onChange={(e) => updatePagination('mode', e.target.value as PaginationMode)}><option value="none">Single page</option><option value="cursor">Cursor</option><option value="page">Page number</option><option value="offset">Offset</option><option value="token">Continuation token</option></select></label>
            {apiMode === 'rest' && pagination.mode !== 'none' && <label className="field"><span>Pagination parameters</span><select value={paginationLocation} onChange={(event) => setPaginationLocation(event.target.value as 'query' | 'body')}><option value="query">Query string</option><option value="body" disabled={restMethod === 'GET'}>Request body</option></select></label>}
            <div className="two-column">
              <label className="field"><span>Page size</span><input type="number" value={pagination.page_size} onChange={(e) => updatePagination('page_size', Number(e.target.value))} /></label>
              <label className="field"><span>Pages</span><div className="pages-control"><select value={pagination.page_count === 'all' ? 'all' : 'count'} onChange={(e) => updatePagination('page_count', e.target.value === 'all' ? 'all' : 1)}><option value="count">Number</option><option value="all">All</option></select>{pagination.page_count !== 'all' && <input aria-label="Number of pages" type="number" min="1" value={pagination.page_count} onChange={(e) => updatePagination('page_count', Math.max(1, Number(e.target.value)))} />}</div></label>
            </div>
            <label className="field"><span>Items path</span><input value={pagination.items_path} onChange={(e) => updatePagination('items_path', e.target.value)} placeholder={apiMode === 'graphql' ? 'data.records.edges' : 'items (blank for a root array)'} /></label>
            <label className="field"><span>Record path within each item</span><input value={pagination.record_path || ''} onChange={(e) => updatePagination('record_path', e.target.value)} placeholder="node (optional)" /></label>

            {pagination.mode === 'cursor' && <>
              <div className="two-column"><label className="field"><span>Cursor variable</span><input value={pagination.cursor_variable} onChange={(e) => updatePagination('cursor_variable', e.target.value)} /></label><label className="field"><span>Size variable</span><input value={pagination.cursor_page_size_variable} onChange={(e) => updatePagination('cursor_page_size_variable', e.target.value)} /></label></div>
              <label className="field"><span>Has-next path</span><input value={pagination.has_next_page_path} onChange={(e) => updatePagination('has_next_page_path', e.target.value)} /></label>
              <label className="field"><span>Next-cursor path</span><input value={pagination.next_cursor_path} onChange={(e) => updatePagination('next_cursor_path', e.target.value)} /></label>
            </>}
            {pagination.mode === 'page' && <>
              <div className="two-column"><label className="field"><span>Page variable</span><input value={pagination.page_variable} onChange={(e) => updatePagination('page_variable', e.target.value)} /></label><label className="field"><span>Size variable</span><input value={pagination.page_size_variable} onChange={(e) => updatePagination('page_size_variable', e.target.value)} /></label></div>
              <label className="field"><span>Total-pages path</span><input value={pagination.total_pages_path || ''} onChange={(e) => updatePagination('total_pages_path', e.target.value)} placeholder="Optional" /></label>
            </>}
            {pagination.mode === 'offset' && <div className="two-column"><label className="field"><span>Offset variable</span><input value={pagination.offset_variable} onChange={(e) => updatePagination('offset_variable', e.target.value)} /></label><label className="field"><span>Limit variable</span><input value={pagination.limit_variable} onChange={(e) => updatePagination('limit_variable', e.target.value)} /></label></div>}
            {pagination.mode === 'token' && <div className="two-column"><label className="field"><span>Token variable</span><input value={pagination.token_variable} onChange={(e) => updatePagination('token_variable', e.target.value)} /></label><label className="field"><span>Next-token path</span><input value={pagination.next_token_path} onChange={(e) => updatePagination('next_token_path', e.target.value)} /></label></div>}
            <div className="two-column"><label className="field"><span>Maximum pages</span><input type="number" value={pagination.max_pages} onChange={(e) => updatePagination('max_pages', Number(e.target.value))} /></label><label className="field"><span>Delay (ms)</span><input type="number" value={pagination.delay_ms} onChange={(e) => updatePagination('delay_ms', Number(e.target.value))} /></label></div>
            <div className="two-column"><label className="field"><span>Timeout (seconds)</span><input type="number" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} /></label><label className="check-field"><input type="checkbox" checked={verifySsl} onChange={(e) => setVerifySsl(e.target.checked)} /><span>Verify SSL</span></label></div>
          </div>
        </section>

        <section className="results-card card">
          <div className="results-header">
            <div className="tabs">
              <button className={resultTab === 'json' ? 'active' : ''} onClick={() => setResultTab('json')}><FileJson size={16} /> {apiMode === 'graphql' ? 'GraphQL JSON' : 'REST JSON'}</button>
              <button className={resultTab === 'table' ? 'active' : ''} onClick={() => setResultTab('table')}><Table2 size={16} /> Table</button>
              <button className={resultTab === 'errors' ? 'active' : ''} onClick={() => setResultTab('errors')}><XCircle size={16} /> Errors {result?.errors.length ? `(${result.errors.length})` : ''}</button>
            </div>
            <div className="export-actions">
              <button disabled={!result} onClick={copyResultsToClipboard} title={`Copy ${resultTab} results`}><Copy size={15} /> Copy</button>
              <button disabled={!result} onClick={() => handleExport('xlsx')}><FileSpreadsheet size={15} /> Excel</button>
              <button disabled={!result} onClick={() => handleExport('csv')}><Download size={15} /> CSV</button>
              <button disabled={!result} onClick={() => handleExport('json')}><FileJson size={15} /> JSON</button>
            </div>
          </div>

          {!result && !running && <div className="empty-results"><div className="empty-icon"><Layers3 size={28} /></div><h3>Your report results will appear here</h3><p>Connect to an endpoint, configure pagination and run the request.</p></div>}
          {running && <div className="empty-results"><LoaderCircle className="spin" size={32} /><h3>Retrieving GraphQL pages</h3><p>The Python service is combining records locally.</p></div>}
          {result && resultTab === 'json' && <pre className="json-view">{JSON.stringify(result.pages.length === 1 ? result.pages[0] : result.pages, null, 2)}</pre>}
          {result && resultTab === 'table' && <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 500).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{row[column] == null ? '' : String(row[column])}</td>)}</tr>)}</tbody></table>{rows.length > 500 && <div className="preview-note">Showing the first 500 rows. Downloads include all {rows.length.toLocaleString()} records.</div>}</div>}
          {result && resultTab === 'errors' && <div className="error-list">{result.errors.length === 0 ? <div className="success-empty"><CheckCircle2 size={28} /><h3>No GraphQL or request errors</h3></div> : result.errors.map((item, index) => <div className="error-item" key={index}><strong>Page {item.page}: {item.message}</strong>{item.details != null && <pre>{JSON.stringify(item.details, null, 2)}</pre>}</div>)}</div>}
        </section>

        <footer className="statusbar">
          <span className={running ? 'working-dot' : 'ready-dot'} /> {status}
          {result && <><span><Database size={13} /> {result.record_count.toLocaleString()} records</span><span><Layers3 size={13} /> {result.page_count} pages</span><span><Clock3 size={13} /> {(result.duration_ms / 1000).toFixed(2)}s</span></>}
        </footer>
      </main>

      {documentationOpen && <>
        <button className="documentation-backdrop" aria-label="Close documentation" onClick={() => setDocumentationOpen(false)} />
        <aside className="documentation-drawer" aria-label="API documentation">
          <header className="documentation-header">
            <div>
              <span className="documentation-eyebrow"><BookOpen size={14} /> API documentation</span>
              <h2>{documentation?.summary || 'Loading documentation…'}</h2>
            </div>
            <button className="documentation-close" aria-label="Close documentation" onClick={() => setDocumentationOpen(false)}><XCircle size={20} /></button>
          </header>
          <div className="documentation-toolbar">
            <button onClick={refreshDocumentation} disabled={documentationLoading || documentationRefreshing}>
              <RefreshCw className={documentationRefreshing ? 'spin' : ''} size={14} /> {documentationRefreshing ? 'Refreshing…' : 'Refresh from source'}
            </button>
            {documentation?.sourceUrl && <a href={documentation.sourceUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open source</a>}
          </div>
          <div className="documentation-content">
            {documentationLoading && <div className="documentation-state"><LoaderCircle className="spin" size={24} /> Loading documentation…</div>}
            {documentationError && <div className="documentation-error"><strong>Documentation could not be refreshed</strong><span>{documentationError}</span>{documentation && <small>The previously cached documentation is still shown below.</small>}</div>}
            {documentation && <>
              <section className="documentation-overview">
                <div className="documentation-badges">
                  <span>{documentation.method}</span><span>{documentation.sourceType}</span>
                  <span className={documentation.status === 'source' ? 'source' : 'generated'}>{documentation.status === 'source' ? 'Source-backed' : 'Generated'}</span>
                  {documentation.deprecated && <span className="deprecated">Deprecated</span>}
                </div>
                <p>{documentation.description || 'No description was supplied by the API publisher.'}</p>
                <dl>
                  <div><dt>Endpoint</dt><dd>{documentation.endpoint}</dd></div>
                  <div><dt>Group</dt><dd>{documentation.group}</dd></div>
                  <div><dt>Source</dt><dd>{documentation.sourceLabel}{documentation.sourceVersion ? ` · ${documentation.sourceVersion}` : ''}</dd></div>
                  {documentation.operationId && <div><dt>Operation ID</dt><dd>{documentation.operationId}</dd></div>}
                  <div><dt>Last refreshed</dt><dd>{new Date(documentation.fetchedAt).toLocaleString()}</dd></div>
                </dl>
              </section>

              <section className="documentation-section">
                <h3>Parameters <small>{documentation.parameters.length}</small></h3>
                {documentation.parameters.length === 0
                  ? <p className="documentation-empty">No parameters are defined.</p>
                  : <div className="documentation-table-wrap"><table><thead><tr><th>Name</th><th>Location</th><th>Type</th><th>Required</th><th>Description / example</th></tr></thead><tbody>{documentation.parameters.map((parameter) => <tr key={`${parameter.location}-${parameter.name}`}><td><code>{parameter.name}</code></td><td>{parameter.location || '—'}</td><td><code>{parameter.type || '—'}{parameter.format ? ` (${parameter.format})` : ''}</code></td><td>{parameter.required ? 'Yes' : 'No'}</td><td>{parameter.description || documentationValue(parameter.example)}</td></tr>)}</tbody></table></div>}
              </section>

              {documentation.requestBody && <section className="documentation-section">
                <h3>Request</h3>
                <p className="documentation-meta">{documentation.requestBody.contentType || 'Content type not specified'}{documentation.requestBody.required ? ' · required' : ''}</p>
                {documentation.requestBody.description && <p>{documentation.requestBody.description}</p>}
                {documentation.requestBody.schema != null && <><h4>Schema</h4><pre>{documentationValue(documentation.requestBody.schema)}</pre></>}
                <h4>Safe example</h4><pre>{documentationValue(documentation.requestBody.example)}</pre>
              </section>}

              {documentation.graphql && <section className="documentation-section">
                <h3>GraphQL schema</h3>
                <dl className="documentation-graphql-summary"><div><dt>Root field</dt><dd><code>{documentation.graphql.rootField || 'Unknown'}</code></dd></div><div><dt>Return type</dt><dd><code>{documentation.graphql.returnType || 'Not supplied'}</code></dd></div></dl>
                <h4>Arguments</h4>
                {(documentation.graphql.arguments || []).length === 0
                  ? <p className="documentation-empty">No arguments are defined.</p>
                  : <div className="documentation-argument-list">{documentation.graphql.arguments?.map((argument) => <details key={argument.name} className="documentation-argument"><summary><span><code>{argument.name}</code>{argument.required && <em>Required</em>}</span><code>{argument.type || 'Unknown'}</code><small>{(argument.inputFields || []).length} input field{(argument.inputFields || []).length === 1 ? '' : 's'}</small><ChevronRight size={15} /></summary><div className="documentation-argument-content"><p>{argument.description || 'No argument description supplied.'}</p>{argument.enumValues && argument.enumValues.length > 0 && <p><strong>Allowed values:</strong> {argument.enumValues.join(', ')}</p>}{argument.default != null && <p><strong>Default:</strong> <code>{documentationValue(argument.default)}</code></p>}<div className="documentation-argument-actions"><button onClick={() => copyArgumentExample(argument)}>Copy example</button></div><pre>{documentationValue({ [argument.name]: argument.example })}</pre><DocumentationInputFields fields={argument.inputFields || []} /></div></details>)}</div>}
                <h4>Available result fields</h4>
                {(documentation.graphql.fields || []).length === 0
                  ? <p className="documentation-empty">No immediate result fields were supplied.</p>
                  : <div className="documentation-field-list">{documentation.graphql.fields?.map((field) => <div key={field.name}><span><code>{field.name}</code><small>{field.type}</small></span><p>{field.description || 'No field description supplied.'}</p></div>)}</div>}
              </section>}

              <section className="documentation-section">
                <h3>Responses <small>{documentation.responses.length}</small></h3>
                {documentation.responses.length === 0
                  ? <p className="documentation-empty">The source does not define REST response metadata.</p>
                  : documentation.responses.map((response) => <details key={response.status}><summary><span>{response.status}</span>{response.description || 'Response'}</summary>{response.schema != null && <pre>{documentationValue(response.schema)}</pre>}{response.example != null && <><h4>Example</h4><pre>{documentationValue(response.example)}</pre></>}</details>)}
              </section>

              {documentation.pagination && <section className="documentation-section"><h3>Pagination</h3><dl><div><dt>Strategy</dt><dd>{documentation.pagination.mode || 'none'}</dd></div><div><dt>Items path</dt><dd><code>{documentation.pagination.itemsPath || 'Root response'}</code></dd></div><div><dt>Page size</dt><dd>{documentation.pagination.pageSize}</dd></div><div><dt>Maximum pages</dt><dd>{documentation.pagination.maximumPages}</dd></div></dl></section>}
            </>}
          </div>
        </aside>
      </>}
    </div>
  )
}

export default App
