import ExcelJS from 'exceljs'

export type ExportFormat = 'xlsx' | 'csv' | 'json'

export interface ClientExportPayload {
  format: ExportFormat
  records: Record<string, unknown>[]
  query?: string
  variables?: Record<string, unknown>
  endpoint?: string
  run_summary?: Record<string, unknown>
  errors?: Array<{ page?: number; message?: string; details?: unknown }>
}

const RESULT_COLLECTION_KEYS = new Set(['data', 'edges', 'items', 'nodes', 'records', 'results', 'value', 'values'])
const FORMULA_PREFIX = /^[=+\-@]/
const MAX_CELL_TEXT = 32_767

type RecordCollection = { path: string[]; records: Record<string, unknown>[] }

function safeText(value: string): string {
  const cleaned = Array.from(value).filter((character) => {
    const code = character.charCodeAt(0)
    return code >= 32 || code === 9 || code === 10 || code === 13
  }).join('')
  const protectedValue = FORMULA_PREFIX.test(cleaned.trimStart()) ? `'${cleaned}` : cleaned
  return protectedValue.length <= MAX_CELL_TEXT
    ? protectedValue
    : `${protectedValue.slice(0, MAX_CELL_TEXT - 20)}… [truncated]`
}

function cellValue(value: unknown): string | number | boolean | Date | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number' || typeof value === 'boolean' || value instanceof Date) return value
  if (typeof value === 'string') return safeText(value)
  return safeText(JSON.stringify(value))
}

function flattenRecord(record: Record<string, unknown>, prefix = ''): Record<string, unknown> {
  const output: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(record)) {
    const column = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(output, flattenRecord(value as Record<string, unknown>, column))
    } else {
      output[column] = Array.isArray(value) ? JSON.stringify(value) : value
    }
  }
  return output
}

function flattenRecords(records: Record<string, unknown>[]) {
  const rows = records.map((record) => flattenRecord(record))
  const columns: string[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    for (const column of Object.keys(row)) {
      if (seen.has(column)) continue
      seen.add(column)
      columns.push(column)
    }
  }
  return { columns, rows }
}

function nestedRecordArrays(value: unknown, path: string[] = []): RecordCollection[] {
  if (Array.isArray(value)) {
    return value.length > 0 && value.every((item) => item && typeof item === 'object' && !Array.isArray(item))
      ? [{ path, records: value as Record<string, unknown>[] }]
      : []
  }
  if (!value || typeof value !== 'object') return []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    nestedRecordArrays(child, [...path, key]),
  )
}

function selectTabularRecords(records: Record<string, unknown>[]) {
  const recordsLookTabular = records.length > 1 && records.some((record) =>
    Object.values(record).some((value) => value === null || typeof value !== 'object'),
  )
  if (recordsLookTabular) return { dataRecords: records, summaryRecords: null, resultPath: null }

  const candidates = new Map<string, RecordCollection>()
  const preferredPaths = new Set<string>()
  for (const record of records) {
    const hasRootScalar = Object.values(record).some((value) => value === null || typeof value !== 'object')
    for (const candidate of nestedRecordArrays(record)) {
      const finalKey = candidate.path.at(-1)?.toLowerCase() ?? ''
      const key = candidate.path.join('.')
      const current = candidates.get(key)
      candidates.set(key, {
        path: candidate.path,
        records: [...(current?.records ?? []), ...candidate.records],
      })
      if (!hasRootScalar || RESULT_COLLECTION_KEYS.has(finalKey)) preferredPaths.add(key)
    }
  }

  const preferredCandidates = Array.from(candidates.entries())
    .filter(([key]) => preferredPaths.has(key))
    .map(([, candidate]) => candidate)
  const selectableCandidates = preferredCandidates.length > 0
    ? preferredCandidates
    : candidates.size === 1
      ? Array.from(candidates.values())
      : []
  const selected = selectableCandidates.sort((left, right) =>
    right.records.length - left.records.length || right.path.length - left.path.length,
  )[0]
  if (!selected) return { dataRecords: records, summaryRecords: null, resultPath: null }
  return {
    dataRecords: selected.records,
    summaryRecords: records.map((record) => summarizeRecord(record, selected.path, selected.records.length)),
    resultPath: selected.path.join('.'),
  }
}

function summarizeRecord(record: Record<string, unknown>, path: string[], totalRecords: number): Record<string, unknown> {
  const clone = structuredClone(record)
  let current: Record<string, unknown> = clone
  for (const key of path.slice(0, -1)) {
    const next = current[key]
    if (!next || typeof next !== 'object' || Array.isArray(next)) return clone
    current = next as Record<string, unknown>
  }
  const finalKey = path.at(-1)
  if (finalKey) current[finalKey] = `[${totalRecords} records exported to the Data sheet]`
  return clone
}

function styleTabularSheet(
  worksheet: ExcelJS.Worksheet,
  columns: string[],
  rows: Record<string, unknown>[],
) {
  if (columns.length === 0) {
    worksheet.addRow(['No records returned'])
    return
  }
  worksheet.addRow(columns.map(safeText))
  for (const row of rows) worksheet.addRow(columns.map((column) => cellValue(row[column])))
  const header = worksheet.getRow(1)
  header.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  header.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF2563EB' } }
  header.alignment = { vertical: 'middle' }
  worksheet.views = [{ state: 'frozen', ySplit: 1 }]
  worksheet.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: Math.max(1, rows.length + 1), column: columns.length },
  }
  columns.forEach((column, index) => {
    const sampleLengths = rows.slice(0, 200).map((row) => String(row[column] ?? '').length)
    worksheet.getColumn(index + 1).width = Math.min(Math.max(column.length, ...sampleLengths, 8) + 2, 55)
  })
}

function addKeyValueSheet(workbook: ExcelJS.Workbook, name: string, values: Record<string, unknown>) {
  const worksheet = workbook.addWorksheet(name)
  worksheet.addRow(['Metric', 'Value'])
  for (const [key, value] of Object.entries(values)) worksheet.addRow([safeText(key), cellValue(value)])
  const header = worksheet.getRow(1)
  header.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  header.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF2563EB' } }
  worksheet.getColumn(1).width = 28
  worksheet.getColumn(2).width = 80
  worksheet.getColumn(2).alignment = { wrapText: true, vertical: 'top' }
}

async function createWorkbook(payload: ClientExportPayload): Promise<Blob> {
  const { dataRecords, summaryRecords, resultPath } = selectTabularRecords(payload.records)
  const workbook = new ExcelJS.Workbook()
  workbook.creator = "Ossy's API Hub"
  workbook.created = new Date()

  const data = flattenRecords(dataRecords)
  styleTabularSheet(workbook.addWorksheet('Data'), data.columns, data.rows)

  if (summaryRecords) {
    const summary = flattenRecords(summaryRecords)
    styleTabularSheet(workbook.addWorksheet('Response Summary'), summary.columns, summary.rows)
  }

  addKeyValueSheet(workbook, 'Run Summary', {
    Endpoint: payload.endpoint ?? '',
    ...(payload.run_summary ?? {}),
    ...(resultPath ? { 'Expanded result path': resultPath } : {}),
  })

  const querySheet = workbook.addWorksheet('Query')
  querySheet.addRow(['Query or request'])
  querySheet.addRow([safeText(payload.query ?? '')])
  querySheet.addRow([])
  querySheet.addRow(['Variables'])
  querySheet.addRow([safeText(JSON.stringify(payload.variables ?? {}, null, 2))])
  for (const rowNumber of [1, 4]) {
    const cell = querySheet.getCell(rowNumber, 1)
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' } }
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF2563EB' } }
  }
  querySheet.getColumn(1).width = 120
  querySheet.getCell('A2').alignment = { wrapText: true, vertical: 'top' }
  querySheet.getCell('A5').alignment = { wrapText: true, vertical: 'top' }

  const errors = (payload.errors ?? []).map((error) => ({
    Page: error.page,
    Message: error.message,
    Details: error.details === undefined ? '' : JSON.stringify(error.details),
  }))
  styleTabularSheet(workbook.addWorksheet('Errors'), ['Page', 'Message', 'Details'], errors)

  const buffer = await workbook.xlsx.writeBuffer()
  return new Blob([new Uint8Array(buffer)], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

function csvCell(value: unknown): string {
  const text = String(cellValue(value) ?? '')
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function createCsv(records: Record<string, unknown>[]): Blob {
  const { dataRecords } = selectTabularRecords(records)
  const { columns, rows } = flattenRecords(dataRecords)
  const lines = [columns.map(csvCell).join(',')]
  for (const row of rows) lines.push(columns.map((column) => csvCell(row[column])).join(','))
  return new Blob([`\uFEFF${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export async function downloadClientExport(payload: ClientExportPayload, filename: string) {
  downloadBlob(await createClientExportBlob(payload), filename)
}

export async function createClientExportBlob(payload: ClientExportPayload): Promise<Blob> {
  return payload.format === 'xlsx'
    ? await createWorkbook(payload)
    : payload.format === 'csv'
      ? createCsv(payload.records)
      : new Blob([JSON.stringify(payload.records, null, 2)], { type: 'application/json;charset=utf-8' })
}
