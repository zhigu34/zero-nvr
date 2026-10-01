/**
 * Shared value formatters.
 *
 * These were re-implemented per view: `formatBytes` twice byte-for-byte,
 * `formatTime` eight times with drifting `Intl.DateTimeFormat` option sets, and
 * `formatDuration` three times. Because each copy built its own option object,
 * the same timestamp could render with seconds in one panel and without them in
 * the next, and fixing that meant finding every copy.
 *
 * The `Intl` option sets are exported as named presets so a call site states
 * *what* it wants ("month/day with seconds") instead of re-listing options, and
 * a change to a preset applies everywhere consistently.
 */

/** Month, day, hour, minute, second — 24-hour. The most common preset. */
export const DATE_TIME_SECONDS: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false
}

/** Month, day, hour, minute — 24-hour, no seconds. */
export const DATE_TIME_MINUTES: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false
}

/** Month, day, year, hour, minute — no seconds. */
export const DATE_TIME_WITH_YEAR: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit"
}

/** Month, day, year, hour, minute, second — no explicit `hour12`, so the
 *  locale default applies. Kept distinct because it renders differently from
 *  `DATE_TIME_SECONDS` in 12-hour locales. */
export const DATE_TIME_WITH_YEAR_SECONDS: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit"
}

/** Hour and minute only — 24-hour. For "today at" style columns. */
export const TIME_ONLY: Intl.DateTimeFormatOptions = {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false
}

interface FormatOptions {
  /** Text for a missing value. Defaults to an em dash. */
  fallback?: string
  /** Active app locale; callers pass `locale.value` from `useI18n`. */
  locale?: string
  /** Return the raw input instead of the fallback when it is unparseable. */
  invalidAsInput?: boolean
}

/**
 * Format an ISO 8601 timestamp with an explicit `Intl` option set.
 *
 * `locale` is a parameter rather than being read here because the app locale is
 * reactive i18n state owned by the calling component; a module-level lookup
 * would not re-render on change.
 */
export function formatDateTime(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions,
  { fallback = "—", locale = "en-US", invalidAsInput = false }: FormatOptions = {}
): string {
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return invalidAsInput ? value : fallback
  }
  return new Intl.DateTimeFormat(locale, options).format(date)
}

/**
 * Render a byte count as `"<amount> <unit>"` with one decimal place above
 * bytes.
 *
 * StorageView uses a different precision rule (see `formatBytesAdaptive`).
 * Unifying the two would change displayed sizes, so they stay separate until
 * that is a deliberate product decision.
 */
export function formatBytes(
  value: number | null | undefined,
  { fallback = "—" }: FormatOptions = {}
): string {
  if (value === null || value === undefined) return fallback
  const units = ["B", "KB", "MB", "GB", "TB"]
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

/**
 * Byte count with precision scaled to magnitude (0 / 1 / 2 decimals) and a
 * peta-byte unit.
 *
 * This is the storage-capacity presentation: an operator comparing a 100 TB
 * array against its quota needs more significant digits than a "1.5 MB" log
 * row, hence the separate rule.
 */
export function formatBytesAdaptive(
  value: number | null | undefined,
  { fallback = "—" }: FormatOptions = {}
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return fallback
  }
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  const digits = amount >= 100 || index === 0 ? 0 : amount >= 10 ? 1 : 2
  return `${amount.toFixed(digits)} ${units[index]}`
}
