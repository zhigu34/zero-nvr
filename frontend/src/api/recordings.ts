import { apiRequest } from "./client"
import { generateUUID } from "../utils/uuid"

export interface RecordingScheduleWindow {
  days: number[]
  start: string
  end: string
}

export interface RecordingPolicy {
  id: string
  camera_id: string
  baseline_mode: "continuous" | "schedule" | "disabled"
  schedule: {
    weekly?: RecordingScheduleWindow[]
  }
  schedule_timezone: string | null
  event_recording_enabled: boolean
  event_filter: {
    labels?: string[]
    zones?: string[]
    min_confidence?: number
  }
  segment_target_seconds: number
  pre_roll_seconds: number
  post_roll_seconds: number
  storage_target_id: string | null
  retention_policy_id: string | null
  enabled: boolean
  runtime: RecordingRuntime | null
}

/**
 * Observed recorder state.
 *
 * `recording` / `stream_online` are observations from the media runtime:
 * `true` means confirmed recording, `false` means confirmed not recording,
 * and `null` means it could not be observed at all (media runtime
 * unreachable). Never treat `null` as "not recording".
 */
export interface RecordingRuntime {
  desired_mode: "persistent" | "prebuffer" | "off"
  recording: boolean | null
  stream_online?: boolean | null
  changed: boolean
  assumed_existing_mode: boolean
  observed_at?: string | null
}

export interface RecordingPolicyPut {
  baseline_mode: "continuous" | "schedule" | "disabled"
  schedule: {
    weekly?: RecordingScheduleWindow[]
  }
  schedule_timezone: string | null
  event_recording_enabled: boolean
  event_filter: {
    labels?: string[]
    zones?: string[]
    min_confidence?: number
  }
  segment_target_seconds: number
  pre_roll_seconds: number
  post_roll_seconds: number
  storage_target_id: string | null
  retention_policy_id: string | null
  enabled: boolean
}

export function listRecordingPolicies(): Promise<RecordingPolicy[]> {
  return apiRequest<RecordingPolicy[]>("/recording-policies")
}

export function getRecordingPolicy(
  cameraId: string
): Promise<RecordingPolicy> {
  return apiRequest<RecordingPolicy>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-policy`
  )
}

export function putRecordingPolicy(
  cameraId: string,
  body: RecordingPolicyPut
): Promise<RecordingPolicy> {
  return apiRequest<RecordingPolicy>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-policy`,
    {
      method: "PUT",
      json: body
    }
  )
}


export interface RecordingProtection {
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

export function listRecordingProtections(
  cameraId: string
): Promise<RecordingProtection[]> {
  return apiRequest<RecordingProtection[]>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-protections`
  )
}

export function createRecordingProtection(
  cameraId: string,
  body: {
    started_at: string
    ended_at: string
    reason: string
    expires_at: string | null
  }
): Promise<RecordingProtection> {
  return apiRequest<RecordingProtection>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-protections`,
    {
      method: "POST",
      json: body
    }
  )
}

export function updateRecordingProtection(
  protectionId: string,
  body: {
    started_at: string
    ended_at: string
    reason: string
    expires_at: string | null
  }
): Promise<RecordingProtection> {
  return apiRequest<RecordingProtection>(
    `/recording-protections/${encodeURIComponent(protectionId)}`,
    {
      method: "PUT",
      json: body
    }
  )
}


export function deleteRecordingProtection(
  protectionId: string
): Promise<void> {
  return apiRequest<void>(
    `/recording-protections/${encodeURIComponent(protectionId)}`,
    { method: "DELETE" }
  )
}


export interface RecordingTrigger {
  id: string
  camera_id: string
  type: string
  source: string
  requested_at: string
  pre_roll_seconds: number
  post_roll_seconds: number
  planned_start_at: string
  planned_end_at: string | null
  state: string
  reason: string | null
  correlation_id: string
}

export function listRecordingTriggers(
  cameraId: string
): Promise<RecordingTrigger[]> {
  return apiRequest<RecordingTrigger[]>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-triggers`
  )
}

export function createRecordingTrigger(
  cameraId: string,
  reason: string | null = null
): Promise<RecordingTrigger> {
  return apiRequest<RecordingTrigger>(
    `/cameras/${encodeURIComponent(cameraId)}/recording-triggers`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": generateUUID()
      },
      json: { reason }
    }
  )
}

export function stopRecordingTrigger(
  triggerId: string
): Promise<RecordingTrigger> {
  return apiRequest<RecordingTrigger>(
    `/recording-triggers/${encodeURIComponent(triggerId)}/stop`,
    { method: "POST" }
  )
}

export interface RecordingSegment {
  id: string
  camera_id: string
  stream_profile_id: string | null
  start_at: string
  end_at: string
  duration_ms: number
  timing_status: string
  timing_source: string
  recording_reasons: string[]
  size_bytes: number
  codec: string
  container: string
  integrity_status: string
  completion_reason: string
  created_at: string
}

export interface RecordingSegmentPage {
  items: RecordingSegment[]
  next_cursor: string | null
}

export function listCameraRecordings(
  cameraId: string,
  from?: Date,
  to?: Date,
  limit: number = 200
): Promise<RecordingSegmentPage> {
  const params = new URLSearchParams()
  if (from) params.set("from", from.toISOString())
  if (to) params.set("to", to.toISOString())
  params.set("limit", String(limit))
  return apiRequest<RecordingSegmentPage>(
    `/cameras/${encodeURIComponent(cameraId)}/recordings?${params}`
  )
}
