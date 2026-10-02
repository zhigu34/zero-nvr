/**
 * Turning the operator's wall-clock choice into what the backend will accept.
 *
 * `POST /exports` rejects a naive timestamp with 422 `timezone_required`
 * (`exports/api.py:48-55`), and quietly accepts a *wrong* one. Both failure
 * modes come from the same shortcut, so they are handled here once:
 *
 * - `new Date("2026-10-01T14:30")` parses as **browser-local**, silently
 *   converting a Beijing wall clock to UTC if the browser is in Berlin. The
 *   export then covers the wrong eight hours and still succeeds.
 * - `new Date(...).toISOString()` on a bare string does the same conversion
 *   and additionally throws the operator's intent away.
 *
 * So the timezone is an explicit input, not an implicit environment, and the
 * conversion is done here rather than at each call site.
 */

/** `ExportService.max_range` — a range longer than this is a 400. */
export const EXPORT_MAX_RANGE_MS = 7 * 24 * 60 * 60 * 1000

/**
 * Offset of `timeZone` from UTC, in ms, at the given instant.
 *
 * Computed by formatting the instant in the target zone and reading the
 * difference back, which is the only portable way to get this without a
 * dependency. Returns 0 for an unrecognised zone rather than throwing: the
 * caller surfaces a validation error, and a bad zone must not take the page
 * down.
 */
export function zoneOffsetMs(instant: Date, timeZone: string): number {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).formatToParts(instant)
    const read = (type: string) => Number(parts.find((p) => p.type === type)?.value)
    const asUtc = Date.UTC(
      read("year"),
      read("month") - 1,
      read("day"),
      read("hour"),
      read("minute"),
      read("second"),
    )
    return asUtc - instant.getTime()
  } catch {
    return 0
  }
}

/**
 * A `datetime-local` value (`"2026-10-01T14:30"`) in `timeZone` → UTC ISO.
 *
 * Two passes rather than one: the first offset is looked up at the naive
 * instant, which is wrong by at most the zone's own DST shift, so the result
 * is re-checked at the corrected instant. Without the second pass a range
 * spanning a DST boundary lands an hour out on one side of it.
 */
export function localInputToUtcIso(local: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(local)
  if (!match) return null
  const [, y, mo, d, h, mi, s] = match
  const naive = Date.UTC(+y, +mo - 1, +d, +h, +mi, +(s ?? 0))
  if (Number.isNaN(naive)) return null
  const firstGuess = new Date(naive - zoneOffsetMs(new Date(naive), timeZone))
  const corrected = new Date(naive - zoneOffsetMs(firstGuess, timeZone))
  return corrected.toISOString()
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone })
    return true
  } catch {
    return false
  }
}

/**
 * The inverse of `localInputToUtcIso`: a segment's UTC bounds back into a
 * `datetime-local` value in `timeZone`.
 *
 * This is what "export this recording" does — it hands the segment's own
 * start and end to the form. Round-tripping through this function rather than
 * slicing the ISO string is the point: a segment at `2026-10-01T02:00Z` is
 * 10:00 in Shanghai and 22:00 the previous day in New York, and only the
 * formatted form is correct in both.
 */
export function utcIsoToLocalInput(iso: string, timeZone: string): string {
  const instant = new Date(iso)
  if (Number.isNaN(instant.getTime()) || !isValidTimeZone(timeZone)) return ""
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(instant)
  const read = (type: string) => parts.find((p) => p.type === type)?.value ?? "00"
  return `${read("year")}-${read("month")}-${read("day")}T${read("hour")}:${read("minute")}`
}

export type ExportFormValues = {
  /** `datetime-local` strings, as typed. */
  start: string
  end: string
  /** IANA zone the operator means the wall clock in. */
  timeZone: string
  codecMode: "auto" | "copy" | "h264"
  gapPolicy: "skip" | "fail"
}

export type ExportValidation =
  | { ok: true; startUtc: string; endUtc: string; durationMs: number }
  | { ok: false; error: string }

/**
 * Everything the backend would reject, checked before the request so the
 * operator sees the reason next to the field instead of in a toast.
 *
 * The order is deliberate: an empty form reports the empty field, not the
 * range length, because the range cannot be measured yet.
 */
export function validateExportForm(values: ExportFormValues): ExportValidation {
  if (!values.start) return { ok: false, error: "请选择开始时间" }
  if (!values.end) return { ok: false, error: "请选择结束时间" }
  if (!isValidTimeZone(values.timeZone)) {
    return { ok: false, error: `时区无效：${values.timeZone}` }
  }

  const startUtc = localInputToUtcIso(values.start, values.timeZone)
  const endUtc = localInputToUtcIso(values.end, values.timeZone)
  if (!startUtc || !endUtc) {
    return { ok: false, error: "时间格式无法解析" }
  }

  const durationMs = Date.parse(endUtc) - Date.parse(startUtc)
  if (durationMs <= 0) {
    return { ok: false, error: "结束时间必须晚于开始时间" }
  }
  if (durationMs > EXPORT_MAX_RANGE_MS) {
    return {
      ok: false,
      error: `单次导出最长 7 天，当前选择 ${formatSpan(durationMs)}`,
    }
  }
  return { ok: true, startUtc, endUtc, durationMs }
}

export function formatSpan(ms: number): string {
  const totalMinutes = Math.round(ms / 60000)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分钟`
}

/** 1–720, backend-enforced (`schemas.py:49-53`). */
export function validateShareTtl(hours: number): string | null {
  if (!Number.isFinite(hours) || !Number.isInteger(hours)) return "有效期须为整数小时"
  if (hours < 1 || hours > 720) return "有效期须在 1–720 小时之间"
  return null
}

/** 1–100000, backend-enforced (`schemas.py:54-58`). */
export function validateMaxDownloads(count: number | null): string | null {
  if (count === null || count === undefined) return null
  if (!Number.isInteger(count)) return "下载次数上限须为整数"
  if (count < 1 || count > 100_000) return "下载次数上限须在 1–100000 之间"
  return null
}
