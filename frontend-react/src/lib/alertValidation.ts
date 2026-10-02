/**
 * Client-side mirror of `AlertService.normalize_match` and
 * `normalize_actions` (`backend/app/modules/alerts/service.py:177-345`).
 *
 * Every rule here has a line number in the service. The point is not to
 * re-implement the validator but to let the operator see the reason next to
 * the field instead of in a toast, and to catch the cases that are *not*
 * field-local — chiefly the time window, which the backend only accepts as a
 * complete triple and rejects wholesale otherwise.
 */
import {
  MATCH_KEY_META,
  MATCH_KEYS,
  WEEKDAY_LABEL,
  type AlertMatch,
  type MatchKey,
} from "../api/alerts"

export const MAX_COOLDOWN_SECONDS = 604_800 // 7 days, `schemas.py:17`
export const MAX_DURATION_SECONDS = 86_400
export const MAX_CAMERA_IDS = 256
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/

export type MatchErrors = Partial<Record<MatchKey | "policy", string>>

/**
 * Reads a wire value as a list without discarding entries of the wrong type.
 *
 * The distinction matters: filtering them out would make `["car", 3]` look
 * like a valid one-item list, the form would pass, and the request would fail
 * server-side with a message the operator cannot act on.
 */
function asList(value: unknown): { items: string[]; hasNonString: boolean } {
  if (!Array.isArray(value)) return { items: [], hasNonString: false }
  return {
    items: value.filter((v): v is string => typeof v === "string"),
    hasNonString: value.some((v) => typeof v !== "string"),
  }
}

/**
 * @param draft the form's current values, before merging with the server's
 */
export function validateMatch(draft: AlertMatch): MatchErrors {
  const errors: MatchErrors = {}

  const checks: [MatchKey, number][] = [
    ["sources", 64],
    ["categories", 64],
    ["labels", 128],
    ["zones", 128],
    ["severities", 32],
    ["camera_ids", MAX_CAMERA_IDS],
  ]
  for (const [key, max] of checks) {
    const { items, hasNonString } = asList(draft[key])
    if (hasNonString) {
      errors[key] = "必须是字符串数组"
    } else if (items.length > max) {
      errors[key] = `最多 ${max} 项，当前 ${items.length} 项`
    }
  }

  for (const key of ["sources", "categories", "labels", "zones", "severities"] as const) {
    if (!Array.isArray(draft[key])) continue
    if (asList(draft[key]).items.some((item) => item.trim() === "")) {
      errors[key] = "不能包含空字符串"
    }
  }

  const severities = asList(draft.severities).items
  const badSeverity = severities.find(
    (s) => !["info", "warning", "critical"].includes(s),
  )
  if (badSeverity) {
    errors.severities = `未知的事件严重度：${badSeverity}（只接受 info / warning / critical）`
  }

  if (draft.min_confidence !== undefined && draft.min_confidence !== "") {
    const value = Number(draft.min_confidence)
    if (Number.isNaN(value) || value < 0 || value > 1) {
      errors.min_confidence = "须在 0–1 之间"
    }
  }

  if (draft.min_duration_seconds !== undefined && draft.min_duration_seconds !== "") {
    const value = Number(draft.min_duration_seconds)
    if (Number.isNaN(value) || value < 0 || value > MAX_DURATION_SECONDS) {
      errors.min_duration_seconds = `须在 0–${MAX_DURATION_SECONDS} 秒之间`
    }
  }

  if (draft.weekdays !== undefined) {
    const list = Array.isArray(draft.weekdays) ? draft.weekdays : []
    if (list.some((d) => typeof d !== "number" || d < 0 || d > 6)) {
      errors.weekdays = "取值须为 0–6（周一=0）"
    }
  }

  // The backend treats these three as one unit and rejects the request if any
  // one of them is present without the others (`service.py:307-338`), so the
  // form refuses a partial window instead of sending one and eating a 400.
  const timeStart = draft.time_start as string | undefined
  const timeEnd = draft.time_end as string | undefined
  const timezone = draft.timezone as string | undefined
  const anyTime = Boolean(timeStart || timeEnd || timezone)
  if (anyTime) {
    if (!timeStart || !timeEnd || !timezone) {
      errors.timezone = "开始、结束、时区必须同时填写"
    } else if (!TIME_RE.test(timeStart) || !TIME_RE.test(timeEnd)) {
      errors.time_start = "格式须为 HH:MM"
    } else if (timeStart === timeEnd) {
      errors.time_end = "开始与结束不能相同"
    } else if (!isValidTimeZone(timezone)) {
      errors.timezone = `无法识别的时区：${timezone}`
    }
  }

  return errors
}

export function hasMatchErrors(errors: MatchErrors): boolean {
  return Object.keys(errors).length > 0
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone })
    return true
  } catch {
    return false
  }
}

/** The three-key time window, cleared together or not at all. */
export function clearTimeWindow(draft: AlertMatch): AlertMatch {
  const next = { ...draft }
  delete next.time_start
  delete next.time_end
  delete next.timezone
  return next
}

/**
 * Copy a key out of a recording `event_filter`.
 *
 * Refuses anything whose meaning differs between the two sides — see
 * `MATCH_KEY_META[key].importable` and
 * `docs/D-2-DECISION-MATERIAL.md` §2. The guard lives here rather than in the
 * component so that a future "copy all" button cannot bypass it.
 */
export function importFromRecordingFilter(
  draft: AlertMatch,
  eventFilter: Record<string, unknown> | null | undefined,
  key: MatchKey,
  { allowed }: { allowed: boolean },
): { draft: AlertMatch; copied: boolean; reason?: string } {
  // The key's own metadata is the authority, ANDed with the caller's intent.
  // Checking only `allowed` would let any future caller — a "copy all"
  // button, a keyboard shortcut — push `zones` across and recreate exactly
  // the D-2 hazard this page exists to avoid.
  if (!allowed || !MATCH_KEY_META[key].importable) {
    return { draft, copied: false, reason: MATCH_KEY_META[key].importNote }
  }
  if (!eventFilter || !(key in eventFilter)) {
    return { draft, copied: false, reason: "该机位的录制策略未设置此项" }
  }
  const value = eventFilter[key]
  if (value === undefined || value === null || value === "") {
    return { draft, copied: false, reason: "该机位的录制策略未设置此项" }
  }
  return { draft: { ...draft, [key]: value }, copied: true }
}

/** The keys a recording filter actually carries, for the reference panel. */
export function recordingFilterKeys(
  eventFilter: Record<string, unknown> | null | undefined,
): MatchKey[] {
  if (!eventFilter) return []
  return MATCH_KEYS.filter((key) => key in eventFilter)
}

export function weekdayLabel(day: number): string {
  return `周${WEEKDAY_LABEL[day] ?? day}`
}
