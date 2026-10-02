/**
 * Storage read contract. Mirrors `backend/app/modules/storage/schemas.py`.
 *
 * **The list endpoint carries no capacity.** `StorageTargetView` is
 * {id, type, role, name, enabled, config, credentials_configured} — there is
 * no free/used/percent field anywhere on the read path. Capacity only comes
 * back from `POST /storage/targets/{id}/test`, which actively probes the
 * target and is therefore a side-effecting POST for what a dashboard wants to
 * treat as a read.
 *
 * `probeTarget` is exposed here, but the storage screen must present it as an
 * explicit user-triggered action ("检测容量"), not as something that silently
 * runs on mount, and must not render a waterline before a probe has happened.
 * A fabricated 0% or "—" would be indistinguishable from real data.
 */
import { api } from "./client"

export type StorageTarget = {
  id: string
  type: "local" | "rclone"
  role: "recording" | "archive"
  name: string
  enabled: boolean
  config: Record<string, unknown>
  credentials_configured: boolean
}

export type CapacityLevel = "normal" | "warning" | "high" | "critical"

export type StorageTargetTest = {
  ok: boolean
  type: "local" | "rclone"
  detail: string
  free_bytes: number | null
  total_bytes: number | null
  used_bytes: number | null
  used_percent: number | null
  capacity_level: CapacityLevel | null
  warning_percent: number | null
  high_percent: number | null
  critical_percent: number | null
}

export type RetentionPolicy = {
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

export function listTargets(signal?: AbortSignal) {
  return api.get<StorageTarget[]>("/storage/targets", signal)
}

/** Side-effecting: probes the target. Never call from a mount effect. */
export function probeTarget(id: string) {
  return api.post<StorageTargetTest>(`/storage/targets/${id}/test`)
}

export function listRetentionPolicies(signal?: AbortSignal) {
  return api.get<RetentionPolicy[]>("/storage/retention-policies", signal)
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—"
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

export const CAPACITY_LEVEL_LABEL: Record<CapacityLevel, string> = {
  normal: "正常",
  warning: "接近告警水位",
  high: "高水位",
  critical: "已超临界",
}
