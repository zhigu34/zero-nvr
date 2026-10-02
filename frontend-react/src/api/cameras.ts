/**
 * Read-side camera contract.
 *
 * Mirrors `backend/app/modules/cameras/schemas.py`. Two things this module
 * deliberately does NOT pretend to have:
 *
 * 1. `GET /cameras` returns `CameraSummary`, which has no clock skew and no
 *    stream bindings — those live on `GET /cameras/{id}` (CameraDetail) and
 *    `GET /cameras/{id}/clock`. A list screen that shows either column is
 *    doing N+1 requests; that is a product decision, not an accident, so
 *    this module exposes them as separate calls rather than faking them.
 * 2. `connectivity_status` is a plain `str` on the backend, not a Literal.
 *    It is typed as a union with a fallback here so an unexpected value
 *    degrades to "unknown" instead of rendering blank.
 */
import { api } from "./client"

export type ConnectivityStatus = "online" | "offline" | "degraded" | "unknown"

export type CameraSummary = {
  id: string
  name: string
  enabled: boolean
  maintenance: boolean
  retired_at: string | null
  location: string | null
  storage_label: string | null
  adapter_type: string | null
  time_sync_mode: "monitor" | "manage_ntp" | "ignore"
  ptz_capable: boolean
  manufacturer: string | null
  model: string | null
  form_factor: string
  ip: string | null
  port: number | null
  rtsp_path: string | null
  sub_rtsp_path: string | null
  video_codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  audio_codec: string | null
  connectivity_status: string
  last_probe_at: string | null
  last_online_at: string | null
}

export type StreamPurpose =
  | "RECORD"
  | "LIVE_HIGH"
  | "LIVE_LOW"
  | "AI_DETECT"
  | "SNAPSHOT"
  | "AUDIO"

export type CameraStreamProfile = {
  id: string
  name: string
  width: number | null
  height: number | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
}

export type CameraStreamBinding = {
  purpose: StreamPurpose
  stream_profile_id: string | null
  selection_mode: "auto" | "manual"
}

export type CameraDetail = CameraSummary & {
  streams: CameraStreamProfile[]
  bindings: CameraStreamBinding[]
}

export type CameraClock = {
  camera_id: string
  health: string
  quality: string
  sync_mode: string
  measured_at: string | null
  offset_ms: number | null
  uncertainty_ms: number | null
  rtt_ms: number | null
  device_timezone: string | null
  device_time_source: string | null
  error_code: string | null
}

export const STREAM_PURPOSE_LABEL: Record<StreamPurpose, string> = {
  RECORD: "录像",
  LIVE_HIGH: "实时主码流",
  LIVE_LOW: "实时子码流",
  AI_DETECT: "AI 检测",
  SNAPSHOT: "抓图",
  AUDIO: "音频",
}

/** Backend sends a bare string; anything unrecognised becomes "unknown". */
export function normalizeConnectivity(raw: string): ConnectivityStatus {
  const v = raw?.toLowerCase()
  if (v === "online" || v === "offline" || v === "degraded") return v
  return "unknown"
}

export function listCameras(
  params: { includeRetired?: boolean } = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (params.includeRetired) qs.set("include_retired", "true")
  const suffix = qs.toString() ? `?${qs}` : ""
  return api.get<CameraSummary[]>(`/cameras${suffix}`, signal)
}

export function getCamera(id: string, signal?: AbortSignal) {
  return api.get<CameraDetail>(`/cameras/${id}`, signal)
}

export function getCameraClock(id: string, signal?: AbortSignal) {
  return api.get<CameraClock>(`/cameras/${id}/clock`, signal)
}
