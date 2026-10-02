/**
 * Export + share contract. Mirrors `backend/app/modules/exports/schemas.py`.
 *
 * Three things here contradict what the old Vue "文件" page assumed, and all
 * three change the shape of the screen rather than just its data source:
 *
 * 1. **The unit of export is a camera plus a time range, not a set of
 *    segments.** `ExportCreate` takes `camera_id` + `start_at` + `end_at` and
 *    the backend picks the covering segments itself
 *    (`export.selected_segment_count` comes back afterwards, not before). One
 *    range produces one mp4. The old page's "tick N clips → get N mp4s" has
 *    no endpoint behind it, and inventing one client-side would mean creating
 *    N overlapping exports and hoping they concatenate — they do not.
 *
 * 2. **There is no progress field.** `ExportView` carries `state`,
 *    `started_at`, and `completed_at`, nothing else. A percentage would have
 *    to be invented from elapsed time, which is a lie with a progress bar on
 *    it. `exportStateLabel` maps the state instead.
 *
 * 3. **`Idempotency-Key` is scoped per user and answers a real question.**
 *    The key is hashed with `requested_by` (`service.py:118-121`), so one
 *    user's key never collides with another's. Reusing a key with an
 *    otherwise-identical request returns the existing job rather than
 *    creating a second one; reusing it with a *different* request is a 409
 *    `idempotency_key_conflict`. See `lib/exportMutations.ts` for how the key
 *    is managed, because one of its failure modes is not obvious.
 */
import { api } from "./client"

/**
 * `models.py:53` — a CHECK constraint, so it is exhaustive. Delivered as a
 * bare `str` by the API, therefore a union here plus a fallthrough branch in
 * the label map rather than a cast.
 */
export type ExportState =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED"

export type ExportView = {
  id: string
  camera_id: string
  requested_by: string | null
  start_at: string
  end_at: string
  requested_duration_ms: number
  format: string
  /** `auto` | `copy` | `h264` on the write path; a free string on read. */
  codec_mode: string
  /** `skip` | `fail` on the write path; a free string on read. */
  gap_policy: string
  state: ExportState | string
  size_bytes: number | null
  actual_duration_ms: number | null
  /** Null until the worker has resolved which segments the range covers. */
  selected_segment_count: number | null
  metadata: Record<string, unknown>
  error_code: string | null
  /** Download returns 410 `export_expired` past this instant. */
  expires_at: string
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export type ExportPage = {
  items: ExportView[]
  next_cursor: string | null
}

export type ExportShareView = {
  id: string
  export_id: string
  expires_at: string
  revoked_at: string | null
  max_downloads: number | null
  download_count: number
  last_download_at: string | null
  password_protected: boolean
  created_at: string
}

/** Returned once, at creation. The token is never readable again. */
export type ExportShareCreated = ExportShareView & {
  token: string
  /** Server-relative, e.g. `/api/v1/shared/exports/<token>/download`. */
  download_path: string
}

export type ExportCreate = {
  camera_id: string
  start_at: string
  end_at: string
  format?: "mp4"
  codec_mode?: "auto" | "copy" | "h264"
  gap_policy?: "skip" | "fail"
}

export type ExportShareCreate = {
  password?: string | null
  /** 1–720, backend-enforced. */
  expires_in_hours?: number
  /** 1–100000, backend-enforced. */
  max_downloads?: number | null
}

export type ExportFilters = {
  state?: string
  cursor?: string
  limit?: number
}

/**
 * The idempotency key is a header rather than a body field, so this goes
 * through the shared client's header support instead of a bespoke `fetch` —
 * duplicating the request would also have duplicated the error mapping, and
 * the copy silently lost FastAPI's per-field 422 messages.
 */
export function createExport(
  body: ExportCreate,
  idempotencyKey: string,
): Promise<ExportView> {
  return api.postWithHeaders<ExportView>("/exports", body, {
    "Idempotency-Key": idempotencyKey,
  })
}

export function listExports(
  filters: ExportFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.state) qs.set("state", filters.state)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 50))
  return api.get<ExportPage>(`/exports?${qs}`, signal)
}

export function getExport(exportId: string, signal?: AbortSignal) {
  return api.get<ExportView>(`/exports/${exportId}`, signal)
}

/** Cancels the job and unlinks its output file. */
export function cancelExport(exportId: string) {
  return api.del<void>(`/exports/${exportId}`)
}

/**
 * A browser navigation, not a JSON fetch — the response is the mp4 bytes. The
 * session cookie rides along because this is same-origin, which is exactly
 * why it cannot be turned into `api.get`.
 */
export function exportDownloadPath(exportId: string) {
  return `/api/v1/exports/${exportId}/download`
}

/** Only permitted once the job is COMPLETED (`shares.py:53`). */
export function createExportShare(
  exportId: string,
  body: ExportShareCreate = {},
) {
  return api.post<ExportShareCreated>(`/exports/${exportId}/shares`, body)
}

export function listExportShares(exportId: string, signal?: AbortSignal) {
  return api.get<ExportShareView[]>(`/exports/${exportId}/shares`, signal)
}

export function revokeExportShare(exportId: string, shareId: string) {
  return api.del<void>(`/exports/${exportId}/shares/${shareId}`)
}

/**
 * ⚠️ The public path. `api.py:532-541` hangs this off `share_basic` alone —
 * no `require_permission`, no session. The token *is* the credential, and
 * whoever holds it downloads the video. There is no per-share allowlist and
 * no way to tell from this module whether a reverse proxy in front of the
 * deployment narrows it. Surfaced in the UI as a warning rather than assumed
 * either way; see G-19.
 */
export function sharedExportPath(token: string) {
  return `/api/v1/shared/exports/${token}/download`
}

/* -------------------------------------------------------------------------- */
/* State vocabulary                                                           */
/* -------------------------------------------------------------------------- */

export const EXPORT_STATE: Record<
  string,
  { label: string; tone: "online" | "offline" | "degraded" | "unknown" }
> = {
  PENDING: { label: "排队中", tone: "unknown" },
  RUNNING: { label: "处理中", tone: "degraded" },
  COMPLETED: { label: "已完成", tone: "online" },
  FAILED: { label: "失败", tone: "offline" },
  CANCELLED: { label: "已取消", tone: "unknown" },
  EXPIRED: { label: "已过期", tone: "unknown" },
}

export function exportStateLabel(state: string) {
  return EXPORT_STATE[state]?.label ?? state
}

export function exportStateTone(state: string) {
  return EXPORT_STATE[state]?.tone ?? "unknown"
}

/** Only these two can still change on their own. */
export function isSettled(state: string) {
  return state !== "PENDING" && state !== "RUNNING"
}
