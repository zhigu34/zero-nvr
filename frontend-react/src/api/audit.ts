/**
 * Audit log contract. Mirrors `backend/app/modules/audit/schemas.py` and the
 * `GET /api/v1/audit` route.
 *
 * The list is keyset paginated and filtered server-side, including by camera
 * — and the camera filter is **scope-enforced**: `list_audit_events` passes
 * `allowed_camera_ids` into the query (`api.py:88-94`), so a viewer with a
 * narrowed scope does not see entries for cameras outside it, and asking for
 * one does not widen the result. The page does not need (and must not imply)
 * a client-side scope filter.
 *
 * The one thing the payload cannot answer on its own is **who** acted:
 * `actor_id` is a UUID and `actor_type` is a bare string. Names live in
 * `/users`, which is a separate `user.manage` resource. An administrator has
 * both, so the page joins the two in memory; anyone without `user.manage` sees
 * the raw id rather than a blank. See G-30.
 */
import { api } from "./client"

export type AuditEventView = {
  id: string
  occurred_at: string
  /** Free string — `user` / `system` / … with no enum on the backend. */
  actor_type: string
  actor_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  camera_id: string | null
  request_id: string | null
  correlation_id: string | null
  source_ip: string | null
  client_info: Record<string, unknown> | null
  /** Free string; `SUCCESS` / `DENIED` / … */
  result: string
  reason: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
}

export type AuditPage = {
  items: AuditEventView[]
  next_cursor: string | null
}

export type AuditFilters = {
  actorId?: string
  action?: string
  resourceType?: string
  cameraId?: string
  result?: string
  from?: string
  to?: string
  cursor?: string
  limit?: number
}

export function listAuditEvents(
  filters: AuditFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.actorId) qs.set("actor_id", filters.actorId)
  if (filters.action) qs.set("action", filters.action)
  if (filters.resourceType) qs.set("resource_type", filters.resourceType)
  if (filters.cameraId) qs.set("camera_id", filters.cameraId)
  if (filters.result) qs.set("result", filters.result)
  // Wire aliases are `from`/`to`, not the python parameter names.
  if (filters.from) qs.set("from", filters.from)
  if (filters.to) qs.set("to", filters.to)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 100))
  return api.get<AuditPage>(`/audit?${qs}`, signal)
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Audit actions are dotted strings written at each call site
 * (`"export.cancel"`, `"user.create"`, `"recording.protection.delete"`), and
 * there is no enum. Grouping on the first segment is what makes a wall of
 * them navigable; the full string stays visible so a new action is not filed
 * under a bucket that does not fit.
 */
export const ACTION_GROUP: Record<string, string> = {
  auth: "登录与会话",
  user: "用户与角色",
  role: "用户与角色",
  camera: "机位",
  recording: "录制",
  export: "导出",
  "export_share": "分享链接",
  storage: "存储",
  retention: "保留策略",
  system: "系统设置",
  notification: "通知",
  integration: "集成",
  frigate: "集成",
  configuration: "配置导入导出",
  secret: "密钥",
  alert: "告警",
  backup: "备份",
  maintenance: "维护",
  token: "API 令牌",
  session: "登录与会话",
}

export function actionGroup(action: string): string {
  const head = action.split(".")[0]
  return ACTION_GROUP[head] ?? "其他"
}

const RESULT_TONE: Record<
  string,
  "online" | "offline" | "degraded" | "unknown"
> = {
  SUCCESS: "online",
  OK: "online",
  DENIED: "offline",
  FAILURE: "offline",
  FAILED: "offline",
  ERROR: "offline",
}

export function resultLabel(result: string): string {
  return { SUCCESS: "成功", DENIED: "拒绝", FAILURE: "失败" }[result] ?? result
}

export function resultTone(result: string) {
  return RESULT_TONE[result] ?? "unknown"
}

const ACTOR_TYPE_LABEL: Record<string, string> = {
  user: "用户",
  system: "系统",
  api_token: "API 令牌",
  worker: "后台任务",
}

export function actorTypeLabel(actorType: string): string {
  return ACTOR_TYPE_LABEL[actorType] ?? actorType
}

/**
 * Does this entry carry a field-level change worth diffing?
 *
 * `before`/`after` are free-form dicts the backend fills on some actions and
 * not others, so "no diff" and "the backend did not record one" look the same
 * on screen. The page says which rather than rendering an empty panel.
 */
export function changedKeys(event: AuditEventView): string[] {
  const before = event.before ?? {}
  const after = event.after ?? {}
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .sort()
}
