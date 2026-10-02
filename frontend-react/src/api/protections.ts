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
