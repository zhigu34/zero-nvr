import { apiRequest } from "./client"

export interface CameraSummary {
  id: string
  name: string
  enabled: boolean
  retired_at: string | null
  location: string | null
  storage_label: string | null
  adapter_type: string | null
  ptz_capable: boolean
  talk_capable?: boolean
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
  talk_backchannel_capable: boolean
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

export function listCameras(
  options: { includeRetired?: boolean } = {}
): Promise<CameraSummary[]> {
  const params = new URLSearchParams()
  if (options.includeRetired) {
    params.set("include_retired", "true")
  }
  const suffix = params.size ? `?${params.toString()}` : ""
  return apiRequest<CameraSummary[]>(`/cameras${suffix}`)
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

export interface OnvifImportResult {
  device_id: string
  reconfigured: boolean
  cameras: CameraDetail[]
}

export function importOnvif(
  body: OnvifImportInput
): Promise<OnvifImportResult> {
  return apiRequest<OnvifImportResult>(
    "/cameras/onvif/import",
    {
      method: "POST",
      json: body
    }
  )
}


export interface CameraStreamProfile {
  id: string
  name: string
  adapter_profile_key: string
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  bitrate_kbps: number | null
  gop_seconds: number | null
  audio_codec: string | null
  has_audio: boolean
  status: string
}

export interface CameraStreamBinding {
  purpose:
    | "RECORD"
    | "LIVE_HIGH"
    | "LIVE_LOW"
    | "AI_DETECT"
    | "SNAPSHOT"
    | "AUDIO"
  stream_profile_id: string
  selection_mode: "auto" | "manual"
}

export interface CameraDetail extends CameraSummary {
  streams: CameraStreamProfile[]
  bindings: CameraStreamBinding[]
}

export interface CameraTalkCapability {
  capable: boolean
  ready: boolean
  backend: string | null
  modes: Array<
    "push_to_talk" | "full_duplex"
  >
}

export interface CameraTalkSession {
  id: string
  camera_id: string
  backend: string
  mode: "push_to_talk" | "full_duplex"
  descriptor: Record<string, unknown>
}

export function getCameraTalkCapability(
  cameraId: string
): Promise<CameraTalkCapability> {
  return apiRequest<CameraTalkCapability>(
    `/cameras/${encodeURIComponent(cameraId)}/talk`
  )
}

export function createCameraTalkSession(
  cameraId: string,
  mode: "push_to_talk" | "full_duplex" = "push_to_talk"
): Promise<CameraTalkSession> {
  return apiRequest<CameraTalkSession>(
    `/cameras/${encodeURIComponent(cameraId)}/talk/session`,
    {
      method: "POST",
      json: { mode }
    }
  )
}

export function keepCameraTalkSession(
  cameraId: string,
  talkSessionId: string
): Promise<void> {
  return apiRequest<void>(
    `/cameras/${encodeURIComponent(cameraId)}/talk/session/${encodeURIComponent(talkSessionId)}/keepalive`,
    { method: "POST" }
  )
}

export function stopCameraTalkSession(
  cameraId: string,
  talkSessionId: string
): Promise<void> {
  return apiRequest<void>(
    `/cameras/${encodeURIComponent(cameraId)}/talk/session/${encodeURIComponent(talkSessionId)}`,
    { method: "DELETE" }
  )
}


export function getCamera(cameraId: string): Promise<CameraDetail> {
  return apiRequest<CameraDetail>(
    `/cameras/${encodeURIComponent(cameraId)}`
  )
}

export function updateCamera(
  cameraId: string,
  changes: {
    name?: string
    location?: string | null
    storage_label?: string | null
  }
): Promise<CameraDetail> {
  return apiRequest<CameraDetail>(
    `/cameras/${encodeURIComponent(cameraId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function setCameraEnabled(
  cameraId: string,
  enabled: boolean
): Promise<CameraDetail> {
  return apiRequest<CameraDetail>(
    `/cameras/${encodeURIComponent(cameraId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  )
}

export function retireCamera(
  cameraId: string
): Promise<CameraDetail> {
  return apiRequest<CameraDetail>(
    `/cameras/${encodeURIComponent(cameraId)}/retire`,
    { method: "POST" }
  )
}

export function restoreCamera(
  cameraId: string
): Promise<CameraDetail> {
  return apiRequest<CameraDetail>(
    `/cameras/${encodeURIComponent(cameraId)}/restore`,
    { method: "POST" }
  )
}

export function replaceCameraBindings(
  cameraId: string,
  bindings: CameraStreamBinding[]
): Promise<CameraStreamBinding[]> {
  return apiRequest<CameraStreamBinding[]>(
    `/cameras/${encodeURIComponent(cameraId)}/stream-bindings`,
    {
      method: "PUT",
      json: { bindings }
    }
  )
}


export interface CameraGroup {
  id: string
  name: string
  description: string | null
  parent_id: string | null
  camera_ids: string[]
}

export function listCameraGroups(): Promise<CameraGroup[]> {
  return apiRequest<CameraGroup[]>("/camera-groups")
}

export function createCameraGroup(body: {
  name: string
  description: string | null
  parent_id: string | null
  camera_ids: string[]
}): Promise<CameraGroup> {
  return apiRequest<CameraGroup>("/camera-groups", {
    method: "POST",
    json: body
  })
}

export function updateCameraGroup(
  groupId: string,
  changes: {
    name?: string
    description?: string | null
    parent_id?: string | null
    camera_ids?: string[]
  }
): Promise<CameraGroup> {
  return apiRequest<CameraGroup>(
    `/camera-groups/${encodeURIComponent(groupId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteCameraGroup(groupId: string): Promise<void> {
  return apiRequest<void>(
    `/camera-groups/${encodeURIComponent(groupId)}`,
    { method: "DELETE" }
  )
}


export function moveCameraPtz(
  cameraId: string,
  velocity: {
    pan?: number
    tilt?: number
    zoom?: number
  }
): Promise<{ ok: true }> {
  return apiRequest<{ ok: true }>(
    `/cameras/${encodeURIComponent(cameraId)}/ptz/move`,
    {
      method: "POST",
      json: {
        pan: velocity.pan ?? 0,
        tilt: velocity.tilt ?? 0,
        zoom: velocity.zoom ?? 0
      }
    }
  )
}

export function stopCameraPtz(
  cameraId: string
): Promise<{ ok: true }> {
  return apiRequest<{ ok: true }>(
    `/cameras/${encodeURIComponent(cameraId)}/ptz/stop`,
    { method: "POST" }
  )
}
