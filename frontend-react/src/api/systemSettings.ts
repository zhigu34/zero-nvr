/**
 * System settings read/write contract.
 * Mirrors `backend/app/modules/system/schemas.py:84-195`.
 *
 * Settings are **grouped**, not key-value: `{general, time, runtime}`, and a
 * PATCH may carry any subset of those groups. Each group applies its own
 * `exclude_unset`, so a field left out of a group is untouched while a field
 * left out of the whole request is likewise untouched.
 *
 * Two fields are compatibility aliases and behave asymmetrically, which is
 * easy to get backwards:
 *
 * - `general.display_timezone` is **read-only**. GET populates it from
 *   `time.recording_timezone`, and a PATCH value is redirected there
 *   (`system/api.py:1068`). Writing it is not an error — it just does not go
 *   where it looks like it goes.
 * - `general.camera_ntp_servers` is writable, but a non-empty list **also
 *   forces** `time.managed_camera_ntp_mode` to `manual`, and an empty one
 *   forces it to `dhcp` (`system/api.py:1086`). Editing the two groups
 *   independently therefore has a result the operator did not type.
 *
 * The form therefore writes through `time.*` and shows the `general.*` aliases
 * as read-only mirrors of it, rather than pretending they are two settings.
 */
import { api } from "./client"

export type SystemSettings = {
  general: {
    system_name: string
    /** Read-only mirror of `time.recording_timezone`. */
    display_timezone: string
    /** Read-only mirror of `time.managed_camera_ntp_servers`. */
    camera_ntp_servers: string[]
  }
  time: {
    /**
     * Currently has no consumer: policy evaluation uses each camera's own
     * `schedule_timezone` instead (`recordings/policy.py:187`).
     */
    recording_timezone: string
    managed_camera_ntp_mode: "manual" | "dhcp"
    managed_camera_ntp_servers: string[]
  }
  runtime: RuntimeTuning
}

export type RuntimeTuning = {
  prebuffer_fragment_seconds: number
  prebuffer_buffer_seconds: number
  turn_credential_ttl_seconds: number
  /** Bytes. */
  playback_cache_max_bytes: number
  playback_cache_ttl_seconds: number
  playback_restore_lock_ttl_seconds: number
  live_transcode_max_derivatives: number
  live_transcode_idle_ttl_seconds: number
  live_transcode_lease_ttl_seconds: number
  /** Float seconds, unlike every other duration in this group. */
  live_transcode_startup_timeout_seconds: number
  live_transcode_cpu_threads: number
  /** kbps, not bits per second and not bytes. */
  live_transcode_video_bitrate_kbps: number
}

export type SystemSettingsPatch = {
  general?: { system_name?: string }
  time?: {
    recording_timezone?: string
    managed_camera_ntp_mode?: "manual" | "dhcp"
    managed_camera_ntp_servers?: string[]
  }
  runtime?: Partial<RuntimeTuning>
}

export type SystemInfo = {
  name: string
  version: string
  environment: string
  database_backend: string
}

export type HealthComponent = {
  status: "OK" | "DEGRADED" | "ERROR" | "DISABLED"
  message: string | null
  details: Record<string, unknown>
}

export type SystemHealth = {
  status: HealthComponent["status"]
  components: Record<string, HealthComponent>
}

export type CameraClockDevice = {
  device_id: string
  name: string
  offset_ms: number | null
  uncertainty_ms: number | null
  rtt_ms: number | null
  error_code: string | null
}

export type CameraClockHealth = {
  status: "ok" | "degraded" | "error"
  checked_at: string
  total_devices: number
  ok: number
  degraded: number
  error: number
  results: CameraClockDevice[]
}

export type CameraNtpDeviceResult = {
  device_id: string
  name: string
  status: "UPDATED" | "FAILED"
  verified: boolean
  date_time_type: string | null
  offset_ms: number | null
  rtt_ms: number | null
  error_code: string | null
}

export type CameraNtpApplyResult = {
  mode: "manual" | "dhcp"
  total_devices: number
  updated: number
  failed: number
  results: CameraNtpDeviceResult[]
}

/** System routes carry an extra `/system` prefix on top of `/api/v1`. */
export function getSystemSettings(signal?: AbortSignal) {
  return api.get<SystemSettings>("/system/settings", signal)
}

export function patchSystemSettings(
  body: SystemSettingsPatch,
  signal?: AbortSignal,
) {
  return api.patch<SystemSettings>("/system/settings", body)
}

export function getSystemHealth(signal?: AbortSignal) {
  return api.get<SystemHealth>("/system/health", signal)
}

export function getSystemInfo(signal?: AbortSignal) {
  return api.get<SystemInfo>("/system/info", signal)
}

export function getCameraClockHealth(signal?: AbortSignal) {
  return api.get<CameraClockHealth>("/system/camera-clock-health", signal)
}

/**
 * The only genuinely batch endpoint in the write surface: it walks every
 * managed device and reports per-device outcomes inside a 200 response, so a
 * partial failure is normal rather than exceptional.
 */
export function applyCameraNtp(signal?: AbortSignal) {
  return api.post<CameraNtpApplyResult>(
    "/system/settings/camera-ntp/apply",
    undefined,
    signal,
  )
}
