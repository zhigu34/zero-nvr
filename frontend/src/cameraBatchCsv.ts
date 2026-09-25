export interface CsvRecord {
  line: number
  values: Record<string, string>
}

export interface ParsedCsv {
  headers: string[]
  rows: CsvRecord[]
}

export class CsvParseError extends Error {
  constructor(
    public readonly code:
      | "csv_empty"
      | "csv_unterminated_quote"
      | "csv_duplicate_header"
      | "csv_too_many_rows",
    public readonly line?: number
  ) {
    super(code)
  }
}

function isBlankRow(row: string[]): boolean {
  return row.every((value) => !value.trim())
}

export function parseCsvRecords(
  input: string,
  maxRows = 500
): ParsedCsv {
  const text = input.replace(/^\uFEFF/, "")
  if (!text.trim()) {
    throw new CsvParseError("csv_empty")
  }

  const rows: Array<{ line: number; cells: string[] }> = []
  let cells: string[] = []
  let cell = ""
  let quoted = false
  let line = 1
  let rowLine = 1

  const pushRow = () => {
    cells.push(cell)
    cell = ""
    if (!isBlankRow(cells)) {
      rows.push({ line: rowLine, cells })
    }
    cells = []
    rowLine = line
  }

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]

    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          cell += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        cell += char
        if (char === "\n") line += 1
      }
      continue
    }

    if (char === '"' && cell.length === 0) {
      quoted = true
      continue
    }
    if (char === ",") {
      cells.push(cell)
      cell = ""
      continue
    }
    if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") {
        index += 1
      }
      line += 1
      pushRow()
      rowLine = line
      continue
    }
    cell += char
  }

  if (quoted) {
    throw new CsvParseError("csv_unterminated_quote", rowLine)
  }
  if (cell.length || cells.length) {
    pushRow()
  }

  if (!rows.length) {
    throw new CsvParseError("csv_empty")
  }

  const headers = rows[0].cells.map((value) =>
    value.trim().toLowerCase()
  )
  const seen = new Set<string>()
  for (const header of headers) {
    if (header && seen.has(header)) {
      throw new CsvParseError("csv_duplicate_header", rows[0].line)
    }
    if (header) seen.add(header)
  }

  const dataRows = rows.slice(1)
  if (dataRows.length > maxRows) {
    throw new CsvParseError("csv_too_many_rows")
  }

  return {
    headers,
    rows: dataRows.map(({ line: rowNumber, cells: row }) => ({
      line: rowNumber,
      values: Object.fromEntries(
        headers.map((header, index) => [
          header,
          row[index] ?? ""
        ])
      )
    }))
  }
}
