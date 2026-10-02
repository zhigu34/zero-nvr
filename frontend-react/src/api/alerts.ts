/**
 * Alert policy + alert contract. Mirrors
 * `backend/app/modules/alerts/schemas.py` and the `/alert-policies*` and
 * `/alerts*` routes.
 *
 * ## The one thing this module exists to get right
 *
 * **`PATCH /alert-policies/{id}` replaces `match` wholesale.** It is a plain
 * `dict[str, object] | None` on `AlertPolicyUpdate` — there is no per-field
 * merge anywhere in `alerts/service.py`. So an editor that rebuilds `match`
 * from the fields it happens to show **silently deletes every key it does not
 * know about**, and the request returns 200.
 *
 * That is not hypothetical: the Vue screen this replaces rebuilt the object
 * from zero in `SystemAlertRulesPanel.vue:275-298`, so a rule carrying
 * `severities` lost that field the first time anyone saved it in the UI.
 * Hence `mergeMatch` below, which is the fix, and its tests.
 *
 * ## The two filters are not the same filter
 *
 * `match` and the recording side's `event_filter` overlap on three keys and
 * disagree about two of them. This does **not** merge them — see
 * `docs/D-2-DECISION-MATERIAL.md`. What the page offers instead is a
 * read-only view of the recording filter with a per-key "copy" action, which
 * is correct under every outcome of that decision because it changes no
 * backend behaviour on its own. `MATCH_KEY_META` records *why* each key is or
 * is not safe to copy, so the UI never has to decide that on its own.
 */
import { api } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type AlertSeverity = "info" | "warning" | "critical"

export type AlertState = "OPEN" | "ACKNOWLEDGED" | "RESOLVED"

/**
 * The 12 keys `normalize_match` accepts (`alerts/service.py:27-40`). An
 * unknown key is a 400, and a known key sent in the wrong shape is also a
 * 400 — so this is a whitelist in both directions.
 */
export const MATCH_KEYS = [
  "camera_ids",
  "sources",
  "categories",
  "labels",
  "zones",
  "min_confidence",
  "min_duration_seconds",
  "severities",
  "weekdays",
  "time_start",
  "time_end",
  "timezone",
] as const

export type MatchKey = (typeof MATCH_KEYS)[number]

/** Free-form on the wire: the backend validates the shape, not the type. */
export type AlertMatch = Record<string, unknown>

export type AlertPolicyView = {
  id: string
  name: string
  enabled: boolean
  severity: AlertSeverity
  match: AlertMatch
  actions: Record<string, unknown>
  cooldown_seconds: number
  created_at: string
  updated_at: string
}

export type AlertPolicyCreate = {
  name: string
  enabled?: boolean
  severity?: AlertSeverity
  match?: AlertMatch
  actions?: Record<string, unknown>
  cooldown_seconds?: number
}

export type AlertPolicyUpdate = Partial<AlertPolicyCreate>

export type AlertView = {
  id: string
  policy_id: string | null
  event_id: string
  camera_id: string | null
  severity: string
  title: string
  message: string | null
  state: AlertState
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
  created_at: string
}

export type AlertPage = {
  items: AlertView[]
  next_cursor: string | null
}

export type AlertFilters = {
  cameraId?: string
  state?: string
  severity?: string
  cursor?: string
  limit?: number
}

export function listAlertPolicies(signal?: AbortSignal) {
  return api.get<AlertPolicyView[]>("/alert-policies", signal)
}

export function createAlertPolicy(body: AlertPolicyCreate) {
  return api.post<AlertPolicyView>("/alert-policies", body)
}

export function updateAlertPolicy(
  policyId: string,
  body: AlertPolicyUpdate,
) {
  return api.patch<AlertPolicyView>(`/alert-policies/${policyId}`, body)
}

export function deleteAlertPolicy(policyId: string) {
  return api.del<void>(`/alert-policies/${policyId}`)
}

export function listAlerts(filters: AlertFilters = {}, signal?: AbortSignal) {
  const qs = new URLSearchParams()
  if (filters.cameraId) qs.set("camera_id", filters.cameraId)
  if (filters.state) qs.set("state", filters.state)
  if (filters.severity) qs.set("severity", filters.severity)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 100))
  return api.get<AlertPage>(`/alerts?${qs}`, signal)
}

export function acknowledgeAlert(alertId: string) {
  return api.post<AlertView>(`/alerts/${alertId}/acknowledge`)
}

export function resolveAlert(alertId: string) {
  return api.post<AlertView>(`/alerts/${alertId}/resolve`)
}

/* -------------------------------------------------------------------------- */
/* The merge that prevents silent field loss                                  */
/* -------------------------------------------------------------------------- */

/**
 * Fields the form considers "unset" and will therefore remove.
 *
 * Mirrors the backend's own behaviour: `normalize_match` **omits** empty
 * values rather than storing them (`if items: result[key] = items`), so an
 * empty list and a missing key mean the same thing to it. The form has to
 * agree, or clearing a field would store `[]` and the two would drift.
 */
export function isEmptyMatchValue(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return true
  if (Array.isArray(value)) return value.length === 0
  return false
}

/**
 * Build the `match` to PATCH from what the form holds and what the server
 * already has.
 *
 * The endpoint demands a full replacement, so the replacement has to be
 * *derived from the current state* rather than from the form's field list.
 * Two rules, and they apply to different keys:
 *
 * - **Known keys (`MATCH_KEYS`) are authoritative.** What the draft holds is
 *   what gets stored, including when the operator cleared it. An empty value
 *   removes the key, matching `normalize_match`, which omits empty lists
 *   rather than persisting them.
 * - **Unknown keys are preserved verbatim.** A key this form does not know
 *   about — added to the backend whitelist in a later release, or written by
 *   an API client rather than the UI — passes through untouched.
 *
 * The second rule is the regression fix. The Vue screen this replaces rebuilt
 * the object from zero, so `severities` was lost the first time anyone saved
 * a rule containing it through the UI, with a 200 in response.
 *
 * The coupling to watch: because a known key is authoritative, the editor
 * must render an input for **every** entry in `MATCH_KEYS`. If a key is added
 * to the list without a matching input, saving starts clearing it. That is
 * asserted in `AlertsView.spec.tsx`, not left to review.
 */
export function mergeMatch(
  existing: AlertMatch | null | undefined,
  draft: AlertMatch,
): AlertMatch {
  const out: AlertMatch = { ...(existing ?? {}) }
  for (const key of MATCH_KEYS) {
    const value = draft[key]
    if (isEmptyMatchValue(value)) {
      delete out[key]
    } else {
      out[key] = value
    }
  }
  return out
}

/**
 * Which keys the stored object carries that this form does not render.
 *
 * Surfaced in the editor so an unrecognised field is visible rather than
 * merely preserved — a field that survives every save but is invisible is
 * still a field nobody can correct.
 */
export function unmanagedMatchKeys(
  existing: AlertMatch | null | undefined,
): string[] {
  return Object.keys(existing ?? {}).filter(
    (key) => !(MATCH_KEYS as readonly string[]).includes(key),
  )
}

/* -------------------------------------------------------------------------- */
/* Key metadata — why a key may or may not be copied from a recording filter   */
/* -------------------------------------------------------------------------- */

export type MatchKeyMeta = {
  label: string
  kind: "uuid-list" | "string-list" | "number" | "weekdays" | "time" | "tz"
  /** `normalize_match` ceiling; 0 means "not a list". */
  maxItems: number
  /** Ceiling on the recording side, where the key exists at all. */
  recordingMaxItems: number
  /**
   * Whether copying this key from a recording `event_filter` produces a rule
   * that means the same thing. This is the D-2 question, answered per key.
   */
  importable: boolean
  /** Shown verbatim next to the copy button. */
  importNote: string
}

export const MATCH_KEY_META: Record<MatchKey, MatchKeyMeta> = {
  camera_ids: {
    label: "摄像机",
    kind: "uuid-list",
    maxItems: 256,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧没有这个概念——录制策略按摄像机唯一，范围由所在行决定。",
  },
  sources: {
    label: "事件来源",
    kind: "string-list",
    maxItems: 64,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧的事件过滤不接受此字段。",
  },
  categories: {
    label: "事件类别",
    kind: "string-list",
    maxItems: 64,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧只按标签过滤，不看类别。",
  },
  labels: {
    label: "标签",
    kind: "string-list",
    maxItems: 128,
    recordingMaxItems: 64,
    importable: true,
    // Same judgement on both sides, different ceiling. Copying is safe in one
    // direction only: a recording filter can hold at most 64, which the alert
    // side also accepts.
    importNote: "两侧判定一致；录制侧上限 64，告警侧 128，因此从这里复制总是安全的。",
  },
  zones: {
    label: "区域",
    kind: "string-list",
    maxItems: 128,
    recordingMaxItems: 64,
    importable: false,
    // The decisive D-2 fact. Not a policy preference: the two sides read
    // different fields for the same event.
    importNote:
      "不可直接复制：录制侧读事件的 metadata_json['zones']（全部区域），告警侧读 Event.zone（主区域）。同一事件会出现「录了但没告警」。",
  },
  min_confidence: {
    label: "最低置信度",
    kind: "number",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: true,
    importNote: "两侧语义完全一致（0–1），是唯一可直接对齐的字段。",
  },
  min_duration_seconds: {
    label: "最短持续秒数",
    kind: "number",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧没有此字段。",
  },
  severities: {
    label: "事件严重度",
    kind: "string-list",
    maxItems: 32,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧没有此字段。注意：这是事件严重度，与策略自身的 severity 无关。",
  },
  weekdays: {
    label: "星期",
    kind: "weekdays",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧用 schedule.windows 表达时间窗，结构与语义都不同。",
  },
  time_start: {
    label: "开始时间",
    kind: "time",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧用 schedule.windows 表达时间窗，结构与语义都不同。",
  },
  time_end: {
    label: "结束时间",
    kind: "time",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: false,
    importNote: "录制侧用 schedule.windows 表达时间窗，结构与语义都不同。",
  },
  timezone: {
    label: "时区",
    kind: "tz",
    maxItems: 0,
    recordingMaxItems: 0,
    importable: false,
    importNote: "与开始/结束时间必须同时出现，单独设置会被判为非法。",
  },
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  info: "提示",
  warning: "警告",
  critical: "严重",
}

export function severityLabel(severity: string): string {
  return SEVERITY_LABEL[severity as AlertSeverity] ?? severity
}

export function severityTone(
  severity: string,
): "online" | "degraded" | "offline" | "unknown" {
  if (severity === "critical") return "offline"
  if (severity === "warning") return "degraded"
  if (severity === "info") return "unknown"
  return "unknown"
}

export const ALERT_STATE_LABEL: Record<AlertState, string> = {
  OPEN: "未处理",
  ACKNOWLEDGED: "已确认",
  RESOLVED: "已解决",
}

export function alertStateLabel(state: string): string {
  return ALERT_STATE_LABEL[state as AlertState] ?? state
}

export const WEEKDAY_LABEL = ["一", "二", "三", "四", "五", "六", "日"] as const

export const ACTION_KEYS = [
  "notification_target_ids",
  "protect_recording",
  "protect_before_seconds",
  "protect_after_seconds",
  "protect_expires_days",
] as const

export const ACTION_KEY_LABEL: Record<string, string> = {
  notification_target_ids: "通知目标",
  protect_recording: "保护录像",
  protect_before_seconds: "保护提前秒数",
  protect_after_seconds: "保护延后秒数",
  protect_expires_days: "保护保留天数",
}
