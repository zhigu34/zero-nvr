import { apiRequest } from "./client"

export type StorageTargetType = "local" | "rclone"
export type StorageTargetRole = "recording" | "archive"

export interface StorageTarget {
  id: string
  type: StorageTargetType
  role: StorageTargetRole
  name: string
  enabled: boolean
  config: Record<string, unknown>
  credentials_configured: boolean
}

export interface StorageTargetTest {
  ok: true
  type: StorageTargetType
  detail: string
  free_bytes: number | null
  total_bytes: number | null
  used_bytes: number | null
  used_percent: number | null
  capacity_level:
    | "normal"
    | "warning"
    | "high"
    | "critical"
    | null
  warning_percent: number | null
  high_percent: number | null
  critical_percent: number | null
}

export interface StorageTargetRecordingSwitchResult {
  source_target_id: string
  destination_target_id: string
  explicit_policies_updated: number
  implicit_policies_rebound: number
  default_moved: boolean
  affected_camera_ids: string[]
}

export interface OpenListWebDavCredentials {
  url: string
  username: string
  password: string
}

export interface StorageTargetCreate {
  type: StorageTargetType
  role: StorageTargetRole
  name: string
  enabled: boolean
  config: Record<string, unknown>
  rclone_config?: string | null
  openlist_webdav?: OpenListWebDavCredentials | null
}

export interface RetentionPolicy {
  id: string
  name: string
  scope_type: "GLOBAL" | "CAMERA" | "CAMERA_GROUP"
  scope_id: string | null
  ordinary_keep_days: number
  event_keep_days: number
  manual_keep_days: number
  mode: "BEST_EFFORT" | "HARD"
  require_archive_before_delete: boolean
  enabled: boolean
}

export interface RetentionPolicyCreate {
  name: string
  scope_type: "GLOBAL" | "CAMERA" | "CAMERA_GROUP"
  scope_id: string | null
  ordinary_keep_days: number
  event_keep_days: number
  manual_keep_days: number
  mode: "BEST_EFFORT" | "HARD"
  require_archive_before_delete: boolean
  enabled: boolean
}

export function listStorageTargets(): Promise<StorageTarget[]> {
  return apiRequest<StorageTarget[]>("/storage/targets")
}

export function createStorageTarget(
  body: StorageTargetCreate
): Promise<StorageTarget> {
  return apiRequest<StorageTarget>("/storage/targets", {
    method: "POST",
    json: body
  })
}

export function updateStorageTarget(
  targetId: string,
  changes: Record<string, unknown>
): Promise<StorageTarget> {
  return apiRequest<StorageTarget>(
    `/storage/targets/${encodeURIComponent(targetId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteStorageTarget(targetId: string): Promise<void> {
  return apiRequest<void>(
    `/storage/targets/${encodeURIComponent(targetId)}`,
    { method: "DELETE" }
  )
}

export function switchRecordingTarget(
  sourceTargetId: string,
  destinationTargetId: string
): Promise<StorageTargetRecordingSwitchResult> {
  return apiRequest<StorageTargetRecordingSwitchResult>(
    `/storage/targets/${encodeURIComponent(
      sourceTargetId
    )}/switch-recording`,
    {
      method: "POST",
      json: {
        destination_target_id: destinationTargetId
      }
    }
  )
}

export function testStorageTarget(
  targetId: string
): Promise<StorageTargetTest> {
  return apiRequest<StorageTargetTest>(
    `/storage/targets/${encodeURIComponent(targetId)}/test`,
    { method: "POST" }
  )
}

export function listRetentionPolicies(): Promise<RetentionPolicy[]> {
  return apiRequest<RetentionPolicy[]>("/storage/retention-policies")
}

export function createRetentionPolicy(
  body: RetentionPolicyCreate
): Promise<RetentionPolicy> {
  return apiRequest<RetentionPolicy>(
    "/storage/retention-policies",
    {
      method: "POST",
      json: body
    }
  )
}

export function updateRetentionPolicy(
  policyId: string,
  changes: Partial<RetentionPolicyCreate>
): Promise<RetentionPolicy> {
  return apiRequest<RetentionPolicy>(
    `/storage/retention-policies/${encodeURIComponent(policyId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteRetentionPolicy(policyId: string): Promise<void> {
  return apiRequest<void>(
    `/storage/retention-policies/${encodeURIComponent(policyId)}`,
    { method: "DELETE" }
  )
}
