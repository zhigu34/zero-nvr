/**
 * Recording policy read/write contract.
 * Mirrors `backend/app/modules/recordings/schemas.py`.
 *
 * Three things here are easy to get wrong:
 *
 * 1. **Seconds, not milliseconds, on the write side.** The policy's
 *    `segment_target_seconds` / `pre_roll_seconds` / `post_roll_seconds` are
 *    all seconds, and they are handed to ZLM as seconds (`recordings/runtime.py:201`).
 *    The stored segments are milliseconds (`duration_ms`). The backend does
 *    the conversion nowhere — it happens in the display layer, so a plan page
 *    legitimately shows "300 秒" next to "300000 毫秒".
 *
 * 2. **`runtime` is not decoration.** A policy save can succeed, return 200,
 *    and still not be recording: `recording_stream_offline` and ZLM's
 *    start-timeout are swallowed (`recordings/api.py:648,672`) and surface
 *    only through `runtime.recording` and `runtime.blockers`. A client that
 *    reads only the status code reports success for a camera that is not
 *    recording anything.
 *
 * 3. **`recording` is tri-state.** `null` means the media runtime cannot be
 *    observed at all, which is not the same as `false`. Rendering "未录制"
 *    for an unobservable camera sends the operator to investigate a problem
 *    that may not exist.
 */
import { api } from "./client"

export type BaselineMode = "continuous" | "schedule" | "disabled"

/** `recordings/runtime.py` desired states. */
export type DesiredMode = "persistent" | "prebuffer" | "off"

export type RecordingRuntime = {
  desired_mode: DesiredMode
  /** `null` = not observable. Never coerce this to `false`. */
  recording: boolean | null
  /** `null` = not observable. */
  stream_online: boolean | null
  changed: boolean
  assumed_existing_mode: boolean
  observed_at: string | null
  /** Backend error codes, e.g. `recording_storage_capacity_critical`. */
  blockers: string[]
}

export type ScheduleWindow = {
  /** 0 = Monday … 6 = Sunday. */
  days: number[]
  /** `HH:MM`, 24-hour. */
  start: string
  end: string
}

export type WeeklySchedule = {
  weekly: ScheduleWindow[]
}

export type RecordingPolicyView = {
  id: string
  camera_id: string
  baseline_mode: BaselineMode
  schedule: Record<string, unknown>
  schedule_timezone: string | null
  event_recording_enabled: boolean
  event_filter: Record<string, unknown>
  /** Seconds. */
  segment_target_seconds: number
  /** Seconds. */
  pre_roll_seconds: number
  /** Seconds. */
  post_roll_seconds: number
  storage_target_id: string | null
  retention_policy_id: string | null
  enabled: boolean
  runtime: RecordingRuntime | null
}

export type RecordingPolicyPage = {
  items: RecordingPolicyView[]
}

export type RecordingPolicyPut = {
  baseline_mode: BaselineMode
  schedule?: Record<string, unknown>
  schedule_timezone?: string | null
  event_recording_enabled?: boolean
  event_filter?: Record<string, unknown>
  segment_target_seconds?: number
  pre_roll_seconds?: number
  post_roll_seconds?: number
  storage_target_id?: string | null
  retention_policy_id?: string | null
  enabled?: boolean
}

export function listRecordingPolicies(signal?: AbortSignal) {
  return api.get<RecordingPolicyPage>("/recording-policies", signal)
}

/**
 * 404s with `recording_policy_not_configured` for a camera that has no
 * policy yet, so callers must treat "not configured" as a normal outcome
 * rather than an error to surface.
 */
export function getCameraRecordingPolicy(
  cameraId: string,
  signal?: AbortSignal,
) {
  return api.get<RecordingPolicyView>(
    `/cameras/${cameraId}/recording-policy`,
    signal,
  )
}

/** Upsert: creates the policy when the camera has none. */
export function putCameraRecordingPolicy(
  cameraId: string,
  body: RecordingPolicyPut,
  signal?: AbortSignal,
) {
  return api.put<RecordingPolicyView>(
    `/cameras/${cameraId}/recording-policy`,
    body,
  )
}
