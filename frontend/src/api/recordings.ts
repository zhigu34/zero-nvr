import { apiRequest } from "./client"

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
  runtime: {
    desired_mode: "persistent" | "prebuffer" | "off"
    recording: boolean
    changed: boolean
    assumed_existing_mode: boolean
  } | null
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
        "Idempotency-Key": crypto.randomUUID()
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
