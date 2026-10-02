/**
 * The batch CSV: the operator's spreadsheet, and everything the client can
 * honestly say about it before a single request is sent.
 *
 * ## There is nothing on the server to validate against
 *
 * `POST /cameras/onvif/import` is the only endpoint that "checks" a row, and it
 * **writes** (see the contract's "Batch is 100% client-side" section in
 * `api/onboarding.ts`). So everything in this module is a *parse check* and the
 * UI has to say so: a row that passes here can still fail on the device, and a
 * row that fails here costs nothing. Contract gap **G-39**.
 *
 * ## The quirks a `split(",")` gets wrong
 *
 * All four appear in real files exported from real spreadsheets, and each one
 * silently corrupts the row rather than failing loudly:
 *
 * 1. **UTF-8 BOM.** Excel writes one, and it becomes part of the first header
 *    name (`﻿kind`), so a name-matched lookup finds nothing.
 * 2. **CRLF.** A Windows-exported file leaves a trailing `\r` on every value.
 * 3. **Quoted commas.** A `location` of `A 座, 3 层` splits into two cells and
 *    shifts every later column by one.
 * 4. **Escaped `""`.** A quote inside a quoted field is doubled; reading it
 *    literally truncates the value.
 *
 * ## Headers are matched by name, unknown columns are ignored
 *
 * The file is the operator's, not ours: they will add a `firmware` column and
 * reorder the rest. Matching by position would import the wrong device from the
 * wrong column, and rejecting an extra column would make the feature unusable
 * on the spreadsheets people actually have.
 *
 * ## A password column is expected, and it goes nowhere
 *
 * ONVIF needs a credential and an `rtsp://` URL needs userinfo, so a
 * credential-free template cannot onboard anything. The password therefore
 * travels through this module and is never rendered: no input, no label, no
 * error message, no query key, no toast. `BatchCsvRow.password` is the only
 * place it exists, and the RTSP URL built from it is equally unprintable —
 * which is why the preview shows `main_path`, never the resolved URL.
 */
import {
  CAMERA_LOCATION_MAX,
  CAMERA_NAME_MAX,
  CAMERA_STORAGE_LABEL_MAX,
  ONVIF_PORT_MAX,
  ONVIF_PORT_MIN,
  emptyManualCameraForm,
  emptyOnvifForm,
  type ManualCameraForm,
  type OnvifForm,
} from "../api/onboarding"

/* -------------------------------------------------------------------------- */
/* Columns                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The fifteen columns, in template order.
 *
 * `kind` decides which of the other columns mean anything: an `rtsp` row is
 * described by `main_url`/`sub_url` (or `host` + `main_path`), an `onvif` row by
 * `host` + `onvif_port` + `username`/`password`.
 */
export const BATCH_CSV_HEADERS = [
  "kind",
  "name",
  "location",
  "host",
  "port",
  "onvif_port",
  "username",
  "password",
  "main_path",
  "sub_path",
  "main_url",
  "sub_url",
  "storage_label",
  "group",
  "remark",
] as const

/** 500 rows is already 500 × 10 s of server-side inspection. */
export const BATCH_CSV_MAX_ROWS = 500

/* -------------------------------------------------------------------------- */
/* Tokenizer                                                                   */
/* -------------------------------------------------------------------------- */

export interface CsvRecord {
  /** 1-based physical line, so an error can name the row the operator sees. */
  line: number
  values: Record<string, string>
}

export interface ParsedCsv {
  headers: string[]
  rows: CsvRecord[]
}

/**
 * A file-level failure. Distinct from a row's `errors` because a broken file is
 * worth no batch at all, while a broken row costs only that row.
 */
export class CsvParseError extends Error {
  constructor(
    public readonly code:
      | "csv_empty"
      | "csv_unterminated_quote"
      | "csv_duplicate_header"
      | "csv_too_many_rows",
    public readonly line?: number,
  ) {
    super(code)
  }
}

export function csvParseErrorMessage(error: CsvParseError): string {
  switch (error.code) {
    case "csv_empty":
      return "文件里没有内容。请确认选的是 CSV 文件，且至少有一行表头。"
    case "csv_unterminated_quote":
      return `第 ${error.line ?? "?"} 行的引号没有闭合。含逗号的值需要用双引号包起来。`
    case "csv_duplicate_header":
      return `表头里有重复的列名（第 ${error.line ?? "?"} 行）。同名两列无法区分是哪一列的值。`
    case "csv_too_many_rows":
      return `行数超过上限 ${BATCH_CSV_MAX_ROWS}。请拆成几个文件分别导入。`
    default:
      return error.message
  }
}

function isBlankRow(row: string[]): boolean {
  return row.every((value) => !value.trim())
}

/**
 * Split CSV text into records.
 *
 * A hand-rolled scanner rather than `split(",")`, for the four reasons in the
 * module docblock. Blank lines are dropped rather than becoming empty rows,
 * because a spreadsheet export routinely ends with one.
 */
export function parseCsvRecords(
  input: string,
  maxRows: number = BATCH_CSV_MAX_ROWS,
): ParsedCsv {
  const text = input.replace(/^\uFEFF/, "")
  if (!text.trim()) throw new CsvParseError("csv_empty")

  const rows: Array<{ line: number; cells: string[] }> = []
  let cells: string[] = []
  let cell = ""
  let quoted = false
  let line = 1
  let rowLine = 1

  const pushRow = () => {
    cells.push(cell)
    cell = ""
    if (!isBlankRow(cells)) rows.push({ line: rowLine, cells })
    cells = []
  }

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]

    if (quoted) {
      if (char === '"') {
        // `""` is one literal quote; a lone `"` closes the field.
        if (text[index + 1] === '"') {
          cell += '"'
          index += 1
        } else {
          quoted = false
        }
        continue
      }
      if (char === "\r") {
        // A quoted field may itself span lines, so the newline has to be
        // counted here too or every later line number is off.
        if (text[index + 1] === "\n") index += 1
        cell += "\n"
        line += 1
        continue
      }
      if (char === "\n") {
        cell += "\n"
        line += 1
        continue
      }
      cell += char
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
      if (char === "\r" && text[index + 1] === "\n") index += 1
      line += 1
      pushRow()
      rowLine = line
      continue
    }
    cell += char
  }

  if (quoted) throw new CsvParseError("csv_unterminated_quote", rowLine)
  if (cell.length || cells.length) pushRow()
  if (!rows.length) throw new CsvParseError("csv_empty")

  const headers = rows[0].cells.map((value) => value.trim().toLowerCase())

  // A duplicate column is not an unknown column and is not ignorable: two
  // columns answering to one name makes every value after it a guess.
  const seen = new Set<string>()
  for (const header of headers) {
    if (!header) continue
    if (seen.has(header)) throw new CsvParseError("csv_duplicate_header", rows[0].line)
    seen.add(header)
  }

  const dataRows = rows.slice(1)
  if (dataRows.length > maxRows) throw new CsvParseError("csv_too_many_rows")

  return {
    headers,
    // Keyed by name, not position. Unknown headers land in the map too and are
    // simply never read.
    rows: dataRows.map(({ line: rowNumber, cells: row }) => ({
      line: rowNumber,
      values: Object.fromEntries(
        headers.map((header, index) => [header, row[index] ?? ""]),
      ),
    })),
  }
}

/* -------------------------------------------------------------------------- */
/* Rows                                                                        */
/* -------------------------------------------------------------------------- */

export type BatchRowKind = "onvif" | "rtsp"

export interface BatchCsvRow {
  line: number
  /** `null` when the file did not say, which is itself a per-row error. */
  kind: BatchRowKind | null
  name: string
  location: string
  host: string
  /** From `onvif_port`, falling back to `port`, default 80. */
  onvifPort: number
  /** From `port`, default 554. */
  rtspPort: number
  username: string
  /** Read once, used twice, and never displayed. See the module docblock. */
  password: string
  mainPath: string
  subPath: string
  mainUrl: string
  subUrl: string
  storageLabel: string
  /** Parsed and shown, but the frozen import contract has no field for it. */
  group: string
  remark: string
  /** Per-row problems. Non-empty means this row will not be sent. */
  errors: string[]
}

/** What the row is called in the list. Never falls back to the password. */
export function batchRowLabel(row: BatchCsvRow): string {
  return row.name || row.host || "（未命名）"
}

function isRtspUrl(value: string): boolean {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return false
  }
  return url.protocol === "rtsp:" && url.hostname !== ""
}

/**
 * The bare-host rule, mirrored from `validateOnvifForm`
 * (`cameras/schemas.py:260-272`): the field is a host, not a URL, and the
 * server rejects `://`, `/`, `@` and whitespace outright. Checking it here
 * names the rule instead of returning a 422 about a field the operator filled
 * in with what looks like a perfectly good address.
 */
function isBareHost(value: string): boolean {
  return !/[:/@\s]/.test(value)
}

function csvPort(
  raw: string,
  fallback: number,
  errors: string[],
  field: string,
): number {
  if (!raw) return fallback
  const parsed = Number(raw)
  if (!Number.isInteger(parsed) || parsed < ONVIF_PORT_MIN || parsed > ONVIF_PORT_MAX) {
    errors.push(`${field} 必须是 ${ONVIF_PORT_MIN}–${ONVIF_PORT_MAX} 之间的整数，收到「${raw}」`)
    return fallback
  }
  return parsed
}

/**
 * One record to one row, with everything checkable without a network call.
 *
 * `port` is disambiguated by `kind`: it is the ONVIF port on an `onvif` row and
 * the stream port on an `rtsp` row, because the file has one port column and
 * the two row kinds need different defaults (80 vs 554). `onvif_port` always
 * wins for an `onvif` row, so a file carrying both is unambiguous.
 */
export function batchRowFromRecord(record: CsvRecord): BatchCsvRow {
  const value = (key: string) => (record.values[key] ?? "").trim()
  const errors: string[] = []

  const rawKind = value("kind").toLowerCase()
  let kind: BatchRowKind | null = null
  if (rawKind === "") {
    errors.push("缺少 kind：这一行要填 onvif 还是 rtsp")
  } else if (rawKind === "onvif" || rawKind === "rtsp") {
    kind = rawKind
  } else {
    errors.push(`kind 只接受 onvif 或 rtsp，收到「${rawKind}」`)
  }

  const name = value("name")
  const location = value("location")
  const host = value("host")
  const username = value("username")
  // Deliberately not trimmed: a password is a secret, and quietly rewriting one
  // because a spreadsheet cell had a stray space is how a working device stops
  // being reachable.
  const password = record.values.password ?? ""

  // `port` is read by exactly one row kind, so it is validated exactly once.
  // Validating it for both would report the same bad cell twice under two
  // different column names.
  const rawPort = value("port")
  const onvifPort =
    kind === "rtsp"
      ? 80
      : csvPort(value("onvif_port") || rawPort, 80, errors, "onvif_port")
  const rtspPort = kind === "onvif" ? 554 : csvPort(rawPort, 554, errors, "port")

  const mainPath = value("main_path")
  const subPath = value("sub_path")
  const mainUrl = value("main_url")
  const subUrl = value("sub_url")

  if (kind === "onvif") {
    if (host === "") {
      errors.push("缺少 host：ONVIF 行需要设备地址")
    } else if (!isBareHost(host)) {
      errors.push("host 只填主机名或 IP，不要带 rtsp:// 前缀、路径、端口或账号密码")
    }
    if (name.length > CAMERA_NAME_MAX) {
      errors.push(`name 最长 ${CAMERA_NAME_MAX} 个字符`)
    }
    if (location.length > CAMERA_LOCATION_MAX) {
      errors.push(`location 最长 ${CAMERA_LOCATION_MAX} 个字符`)
    }
    if (value("storage_label").length > CAMERA_STORAGE_LABEL_MAX) {
      errors.push(`storage_label 最长 ${CAMERA_STORAGE_LABEL_MAX} 个字符`)
    }
  }

  if (kind === "rtsp") {
    if (name === "") errors.push("缺少 name：手动添加的机位必须有名称")
    if (mainPath.includes("://") || subPath.includes("://")) {
      errors.push("main_path / sub_path 只填路径，不含 rtsp:// 前缀；完整地址请填 main_url / sub_url")
    }
    if (mainUrl === "" && host === "") {
      errors.push("缺少 host：要么填完整的 main_url，要么填 host 配合 main_path")
    }
    if (mainUrl === "" && mainPath === "") {
      errors.push("缺少 main_path：没有完整 main_url 时，至少要给出主码流路径")
    }
    if (mainUrl !== "" && !isRtspUrl(mainUrl)) {
      errors.push("main_url 必须是 rtsp:// 开头且带主机名的完整地址")
    }
    if (subUrl !== "" && !isRtspUrl(subUrl)) {
      errors.push("sub_url 必须是 rtsp:// 开头且带主机名的完整地址")
    }
    if (subUrl === "" && subPath !== "" && host === "" && mainUrl === "") {
      errors.push("子码流只给了 sub_path：拼地址还需要 host")
    }
  }

  return {
    line: record.line,
    kind,
    name,
    location,
    host,
    onvifPort,
    rtspPort,
    username,
    password,
    mainPath,
    subPath,
    mainUrl,
    subUrl,
    storageLabel: value("storage_label"),
    group: value("group"),
    remark: value("remark"),
    errors,
  }
}

/** Parse a picked file into rows. Throws `CsvParseError` for a broken file. */
export function parseBatchCsv(text: string): BatchCsvRow[] {
  return parseCsvRecords(text).rows.map(batchRowFromRecord)
}

/* -------------------------------------------------------------------------- */
/* Template                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * One example row per `kind`.
 *
 * Two, not one: the `kind` column is what makes the file meaningful, and a
 * template showing only the ONVIF form leaves an operator with a file full of
 * RTSP cameras and no example of what their row should look like.
 */
const TEMPLATE_ROWS = [
  [
    "onvif",
    "前门 ONVIF",
    "A 座, 1 层",
    "192.168.1.64",
    "80",
    "80",
    "admin",
    "在此填设备密码",
    "",
    "",
    "",
    "",
    "店内",
    "园区北门",
    "示例行，可整行删除",
  ],
  [
    "rtsp",
    "停车场 RTSP",
    "B 座 2 层",
    "192.168.1.65",
    "554",
    "",
    "admin",
    "在此填设备密码",
    "Streaming/Channels/101",
    "Streaming/Channels/102",
    "",
    "",
    "店内",
    "园区北门",
    "示例行，可整行删除",
  ],
] as const

function quoteCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/**
 * The downloadable template.
 *
 * CRLF and a BOM, because that is what Excel produces and what this parser
 * handles — the file an operator saves and re-opens must survive a round trip
 * through their own spreadsheet, and the second example row exists to prove a
 * quoted comma works.
 */
export function buildBatchCsvTemplate(): string {
  const lines = [
    BATCH_CSV_HEADERS.join(","),
    ...TEMPLATE_ROWS.map((row) => row.map(quoteCell).join(",")),
  ]
  return `\uFEFF${lines.join("\r\n")}\r\n`
}

/* -------------------------------------------------------------------------- */
/* Row → request bodies                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The ONVIF probe body for a row.
 *
 * `host` is passed through untrimmed-by-the-server: the column was trimmed at
 * parse time, and the server is the authority on the field's exact shape.
 */
export function onvifFormForRow(row: BatchCsvRow): OnvifForm {
  return {
    ...emptyOnvifForm(row.host, row.onvifPort),
    username: row.username,
    password: row.password,
    name: row.name,
    location: row.location,
    storageLabel: row.storageLabel,
    // The batch never lets anyone tick profiles, so the selection is untouched
    // and the caller decides what to send via `profile_tokens`.
    selectedProfileTokens: [],
    selectionTouched: false,
    discoveryCandidateId: null,
  }
}

function rtspHost(host: string): string {
  return host.includes(":") && !host.startsWith("[") ? `[${host}]` : host
}

/**
 * The RTSP URL for one stream.
 *
 * A `main_url` from the file wins. Otherwise the URL is assembled from
 * `host` + `port` + `main_path` with the row's credentials in the userinfo —
 * which is why the result must never be rendered: it carries the password.
 */
export function rtspUrlForRow(
  row: BatchCsvRow,
  path: string,
  override: string,
): string {
  if (override) return override
  if (!row.host || !path) return ""
  const normalized = path.startsWith("/") ? path : `/${path}`
  const hasAuth = row.username !== "" || row.password !== ""
  const auth = hasAuth
    ? `${encodeURIComponent(row.username)}${row.password ? `:${encodeURIComponent(row.password)}` : ""}@`
    : ""
  return `rtsp://${auth}${rtspHost(row.host)}:${row.rtspPort}${normalized}`
}

/**
 * The manual-camera form for an `rtsp` row.
 *
 * `hasSecondary` is derived from the file rather than offered as a choice: an
 * empty `sub_url` / `sub_path` is how "this camera has one stream" is written
 * down, and there is no second-stream detection anywhere in the contract.
 */
export function manualFormForRow(row: BatchCsvRow): ManualCameraForm {
  const subUrl = rtspUrlForRow(row, row.subPath, row.subUrl)
  return {
    ...emptyManualCameraForm(),
    name: row.name,
    location: row.location,
    storageLabel: row.storageLabel,
    primaryName: "主码流",
    primaryUrl: rtspUrlForRow(row, row.mainPath, row.mainUrl),
    secondaryName: "子码流",
    secondaryUrl: subUrl,
    hasSecondary: subUrl !== "",
  }
}
