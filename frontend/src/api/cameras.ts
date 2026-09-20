import { apiRequest } from "./client"

export interface CameraSummary {
  id: string
  name: string
  enabled: boolean
  location: string | null
  storage_label: string | null
  adapter_type: string | null
}

export interface CameraProbeTrack {
  kind: "video" | "audio"
  codec: string | null
  ready: boolean
  width?: number | null
  height?: number | null
  fps?: number | null
  gop_seconds?: number | null
  sample_rate?: number | null
  channels?: number | null
}

export interface CameraProbeStream {
  role: "primary" | "secondary"
  name: string
  video: CameraProbeTrack | null
  audio: CameraProbeTrack | null
}

export interface CameraProbeResult {
  ok: true
  streams: CameraProbeStream[]
}

export interface ManualCameraInput {
  mode: "manual_rtsp"
  name: string
  location: string | null
  storage_label: string | null
  primary_stream: {
    name: string
    rtsp_url: string
  }
  secondary_stream: {
    name: string
    rtsp_url: string
  } | null
}

export interface DiscoveryCandidate {
  id: string
  candidate_key: string
  host: string | null
  port: number | null
  device_service_url: string | null
  display_info: Record<string, unknown>
  state: string
}

export interface DiscoverySession {
  id: string
  method: string
  status: string
  started_at: string
  completed_at: string | null
  candidates: DiscoveryCandidate[]
}

export interface OnvifDeviceInfo {
  manufacturer: string | null
  model: string | null
  firmware_version: string | null
  serial_number: string | null
  hardware_id: string | null
}

export interface OnvifProfile {
  token: string
  name: string
  video_source_token: string | null
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  bitrate_kbps: number | null
  gop_seconds: number | null
  audio_codec: string | null
  has_audio: boolean
  stream_uri_available: boolean
}

export interface OnvifInspection {
  device: OnvifDeviceInfo
  capabilities: string[]
  profiles: OnvifProfile[]
}

export interface OnvifCredentialsInput {
  host: string
  port: number
  username: string
  password: string
}

export interface OnvifImportInput extends OnvifCredentialsInput {
  name: string | null
  location: string | null
  storage_label: string | null
  profile_tokens: string[]
  discovery_candidate_id?: string | null
}

export function listCameras(): Promise<CameraSummary[]> {
  return apiRequest<CameraSummary[]>("/cameras")
}

export function testManualCamera(
  body: ManualCameraInput
): Promise<CameraProbeResult> {
  return apiRequest<CameraProbeResult>("/cameras/test", {
    method: "POST",
    json: body
  })
}

export function createManualCamera(
  body: ManualCameraInput
): Promise<unknown> {
  return apiRequest("/cameras", {
    method: "POST",
    json: body
  })
}

export function discoverOnvif(): Promise<DiscoverySession> {
  return apiRequest<DiscoverySession>("/cameras/discovery", {
    method: "POST"
  })
}

export function inspectOnvif(
  body: OnvifCredentialsInput
): Promise<OnvifInspection> {
  return apiRequest<OnvifInspection>("/cameras/onvif/test", {
    method: "POST",
    json: body
  })
}

export function importOnvif(
  body: OnvifImportInput
): Promise<unknown> {
  return apiRequest("/cameras/onvif/import", {
    method: "POST",
    json: body
  })
}
