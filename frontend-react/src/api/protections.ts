/**
 * Recording-protection contract. Mirrors `recordings/schemas.py:284-307`.
 *
 * This exists as its own module because of one structural fact that the old
 * Vue file page got wrong: **a protection is a time window on a camera, not a
 * flag on a segment.** `RecordingProtectionCreate` takes
 * `{started_at, ended_at, reason, expires_at}` and is scoped to a camera, and
 * there is no `segment_id` anywhere in the model. A recording is protected
 * when it *overlaps* a protection window.
 *
 * That is still enough to render a per-segment "protected" marker, but only
 * by fetching the camera's windows once and intersecting them locally — which
 * is what `isProtected` does. The alternative, a per-segment lookup, does not
 * exist as an endpoint and would be N requests for an N-row table.
 *
 * ## Three write-time traps, all of which produce a 4xx and no protection
 *
 * 1. **Naive datetimes are a hard 422.** The service runs every timestamp
 *    through `require_utc` (`recordings/protection.py:22`), which rejects a
 *    datetime with no offset as `timezone_required` (`core/time.py:48-65`).
 *    A `<input type="datetime-local">` produces exactly that. `localWindowToIso`
 *    is the only way these should reach the wire.
 * 2. **`PUT` replaces the whole object, and `expires_at` is no exception.**
 *    `protection.py:234-237` assigns unconditionally, so omitting `expires_at`
 *    **clears** the expiry rather than keeping it. `buildProtectionBody` always
 *    sends all four fields.
 * 3. **The window is half-open `[started_at, ended_at)`.** Overlap is
 *    `segment.started_at < ended_at AND segment.ended_at > started_at`
 *    (`protection.py:133-134`), and retention applies the identical test
 *    (`storage/retention.py:371-374`). An instant is not a window, and
 *    `ended_at == started_at` is rejected outright.
 *
 * ## Two cross-resource effects the operator cannot see from this screen
 *
 * - A protection **blocks retention**: an overlapping, unexpired window
 *   prevents segment deletion (`storage/retention.py:364-380`), so it silently
 *   inflates disk usage. A form that does not say so is hiding a cost.
 * - **Alerts create protections automatically** from events
 *   (`alerts/service.py:921-927`), so a list of windows can contain rows nobody
 *   made by hand. `created_by` being null is the only hint.
 */
import { api } from "./client"

export type RecordingProtectionView = {
  id: string
  camera_id: string
  started_at: string
  ended_at: string
  reason: string
  created_by: string | null
  expires_at: string | null
  created_at: string
  updated_at: string
}

export function listCameraProtections(
  cameraId: string,
  signal?: AbortSignal,
) {
  return api.get<RecordingProtectionView[]>(
    `/cameras/${cameraId}/recording-protections`,
    signal,
  )
}

export function createCameraProtection(
  cameraId: string,
  body: {
    started_at: string
    ended_at: string
    reason: string
    expires_at?: string | null
  },
) {
  return api.post<RecordingProtectionView>(
    `/cameras/${cameraId}/recording-protections`,
    body,
  )
}

export function updateRecordingProtection(
  protectionId: string,
  body: {
    started_at: string
    ended_at: string
    reason: string
    expires_at?: string | null
  },
) {
  return api.put<RecordingProtectionView>(
    `/recording-protections/${protectionId}`,
    body,
  )
}

export function deleteRecordingProtection(protectionId: string) {
  return api.del<void>(`/recording-protections/${protectionId}`)
}

/**
 * Is this window still in force?
 *
 * Split out because the two questions below need different halves of it: a
 * single instant needs "active *and* containing", a span needs "active"
 * plus a plain interval test. Folding the instant test into the span test is
 * what made an overlapping recording look unprotected.
 *
 * `expires_at` null means **no expiry** — the opposite of the
 * `recording: boolean | null` convention used for runtime state, where null
 * means "cannot observe". Resolved here so the two conventions cannot be
 * confused at a call site.
 */
export function isProtectionActive(
  protection: RecordingProtectionView,
  now: number = Date.now(),
): boolean {
  if (!protection.expires_at) return true
  const expiry = Date.parse(protection.expires_at)
  return Number.isNaN(expiry) ? true : expiry > now
}

/**
 * Does a window cover this single instant?
 *
 * Half-open on both ends, matching how every other interval in this codebase
 * is treated: a recording ending exactly when a protection starts is not
 * covered by it, and a recording starting exactly when one ends is not
 * either. Two recordings that merely touch at a boundary are separate files
 * and only the first is protected.
 */
export function isProtected(
  protection: RecordingProtectionView,
  at: number,
  now: number = Date.now(),
): boolean {
  if (!isProtectionActive(protection, now)) return false
  const start = Date.parse(protection.started_at)
  const end = Date.parse(protection.ended_at)
  if (Number.isNaN(start) || Number.isNaN(end)) return false
  return at >= start && at < end
}

/**
 * Does a window overlap this recording at all?
 *
 * A plain half-open interval intersection, and deliberately *not* a call into
 * `isProtected` with the recording's start: a recording that begins before
 * the window and ends inside it overlaps without its start being covered.
 */
export function overlapsProtection(
  protections: readonly RecordingProtectionView[],
  startAt: string,
  endAt: string,
  now: number = Date.now(),
): boolean {
  const start = Date.parse(startAt)
  const end = Date.parse(endAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return false
  return protections.some((p) => {
    if (!isProtectionActive(p, now)) return false
    const pStart = Date.parse(p.started_at)
    const pEnd = Date.parse(p.ended_at)
    if (Number.isNaN(pStart) || Number.isNaN(pEnd)) return false
    return start < pEnd && pStart < end
  })
}

/* -------------------------------------------------------------------------- */
/* Write-time form                                                            */
/* -------------------------------------------------------------------------- */

export const PROTECTION_REASON_MAX = 1024

export type ProtectionForm = {
  /** Wall clock from a `datetime-local` input, not yet an ISO string. */
  startedAt: string
  endedAt: string
  reason: string
  /** Wall clock or empty. Empty means "never expires", which is `null`. */
  expiresAt: string
}

export type ProtectionFormField = "startedAt" | "endedAt" | "reason" | "expiresAt"

export type ProtectionFormError = { field: ProtectionFormField; message: string }

export type ProtectionBody = {
  started_at: string
  ended_at: string
  reason: string
  expires_at: string | null
}

export function emptyProtectionForm(): ProtectionForm {
  return { startedAt: "", endedAt: "", reason: "", expiresAt: "" }
}

export function protectionFormFromView(view: RecordingProtectionView): ProtectionForm {
  return {
    startedAt: view.started_at,
    endedAt: view.ended_at,
    reason: view.reason,
    expiresAt: view.expires_at ?? "",
  }
}

/**
 * Convert a `datetime-local` value to the offset-bearing ISO the schema wants.
 *
 * `new Date("2026-10-01T14:30")` parses as *browser-local* time. That is the
 * right instant for an operator who typed their own wall clock, and sending the
 * bare string instead is what the server rejects with `timezone_required`. So
 * the conversion happens here, once, and the wire always carries an offset.
 */
export function localWindowToIso(value: string): string | null {
  if (!value.trim()) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

/**
 * Validate against the rules the service actually enforces.
 *
 * `reason` is the subtle one: `min_length=1` on the schema accepts `"   "`, and
 * the service then rejects it after `.strip()` with
 * `recording_protection_reason_required` (`protection.py:186-190`).
 *
 * `expires_at <= now` is rejected too (`recording_protection_expiry_invalid`),
 * which is worth checking locally because "expire in the past" is an easy
 * accident when a form round-trips an existing window.
 */
export function validateProtectionForm(
  form: ProtectionForm,
  now: Date = new Date(),
): ProtectionFormError[] {
  const errors: ProtectionFormError[] = []

  const start = form.startedAt ? new Date(form.startedAt) : null
  const end = form.endedAt ? new Date(form.endedAt) : null

  if (!start || Number.isNaN(start.getTime())) {
    errors.push({ field: "startedAt", message: "请填写开始时间" })
  }
  if (!end || Number.isNaN(end.getTime())) {
    errors.push({ field: "endedAt", message: "请填写结束时间" })
  }
  if (start && end && !Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime())) {
    // Half-open: an instant is not a window, and the backend rejects it.
    if (end.getTime() <= start.getTime()) {
      errors.push({
        field: "endedAt",
        message: "结束时间必须晚于开始时间——保护区间是左闭右开的，瞬时点不算区间",
      })
    }
  }

  const reason = form.reason.trim()
  if (reason === "") {
    errors.push({ field: "reason", message: "请填写保护原因" })
  } else if (reason.length > PROTECTION_REASON_MAX) {
    errors.push({
      field: "reason",
      message: `原因最长 ${PROTECTION_REASON_MAX} 个字符`,
    })
  }

  if (form.expiresAt.trim()) {
    const expires = new Date(form.expiresAt)
    if (Number.isNaN(expires.getTime())) {
      errors.push({ field: "expiresAt", message: "失效时间无法解析" })
    } else if (expires.getTime() <= now.getTime()) {
      errors.push({ field: "expiresAt", message: "失效时间必须是将来的时间" })
    }
  }

  return errors
}

/**
 * Build the body for both create and update.
 *
 * Always all four fields, because `PUT` is a whole-object replace and
 * `protection.py:234-237` assigns `expires_at` unconditionally — omitting it
 * would clear the expiry rather than keep it. `expires_at: null` means "never
 * expires", which is a real state and not a missing value.
 */
export function buildProtectionBody(form: ProtectionForm): ProtectionBody {
  return {
    started_at: localWindowToIso(form.startedAt) as string,
    ended_at: localWindowToIso(form.endedAt) as string,
    reason: form.reason.trim(),
    expires_at: form.expiresAt.trim()
      ? (localWindowToIso(form.expiresAt) as string)
      : null,
  }
}

/** Whether this window has lapsed — protection gone, but the row remains. */
export function isProtectionExpired(
  view: RecordingProtectionView,
  now: Date = new Date(),
): boolean {
  if (!view.expires_at) return false
  return new Date(view.expires_at).getTime() <= now.getTime()
}
