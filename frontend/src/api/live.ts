import {
  ApiClientError,
  apiRequest,
  type ApiErrorBody
} from "./client"

export type LiveQuality = "auto" | "high" | "low"

export interface CameraLiveStream {
  camera_id: string
  profile_id: string
  purpose: "LIVE_HIGH" | "LIVE_LOW" | "RECORD"
  transport: "hls"
  transports: Array<"webrtc" | "hls">
  hls_url: string
  media_session_id: string
  expires_at: string
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  ice_servers: CameraIceServer[]
  ice_error: string | null
  compatibility?: "h264_transcode" | null
  compatibility_lease_id?: string | null
  compatibility_acceleration?: "cpu" | "nvenc" | "vaapi" | null
}

export function getCameraLiveStream(
  cameraId: string,
  quality: LiveQuality
): Promise<CameraLiveStream> {
  const params = new URLSearchParams({ quality })
  return apiRequest<CameraLiveStream>(
    `/cameras/${encodeURIComponent(cameraId)}/live?${params}`
  )
}


export function getCameraCompatibleLiveStream(
  cameraId: string,
  quality: LiveQuality,
  mediaSessionId: string
): Promise<CameraLiveStream> {
  const params = new URLSearchParams({
    quality,
    media_session_id: mediaSessionId
  })
  return apiRequest<CameraLiveStream>(
    `/cameras/${encodeURIComponent(cameraId)}/live/compatibility?${params}`,
    { method: "POST" }
  )
}

export function keepCameraCompatibilityLease(
  cameraId: string,
  leaseId: string,
  mediaSessionId: string
): Promise<void> {
  const params = new URLSearchParams({
    media_session_id: mediaSessionId
  })
  return apiRequest<void>(
    `/cameras/${encodeURIComponent(cameraId)}/live/compatibility/${encodeURIComponent(leaseId)}/keepalive?${params}`,
    { method: "POST" }
  )
}

export function releaseCameraCompatibilityLease(
  cameraId: string,
  leaseId: string,
  mediaSessionId: string
): Promise<void> {
  const params = new URLSearchParams({
    media_session_id: mediaSessionId
  })
  return apiRequest<void>(
    `/cameras/${encodeURIComponent(cameraId)}/live/compatibility/${encodeURIComponent(leaseId)}?${params}`,
    { method: "DELETE" }
  )
}


export interface CameraLiveDiagnostic {
  camera_id: string
  profile_id: string
  purpose: "LIVE_HIGH" | "LIVE_LOW" | "RECORD"
  state:
    | "source_offline"
    | "video_missing"
    | "video_not_ready"
    | "ready"
  source_online: boolean
  video_present: boolean
  video_ready: boolean
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
}

export function getCameraLiveDiagnostics(
  cameraId: string,
  quality: LiveQuality,
  mediaSessionId: string
): Promise<CameraLiveDiagnostic> {
  const params = new URLSearchParams({
    quality,
    media_session_id: mediaSessionId
  })
  return apiRequest<CameraLiveDiagnostic>(
    `/cameras/${encodeURIComponent(cameraId)}/live/diagnostics?${params}`
  )
}


export interface CameraIceServer {
  urls: string[]
  username: string
  credential: string
  expires_at: string
}

export interface CameraIceServers {
  enabled: boolean
  ice_servers: CameraIceServer[]
}

export function getCameraIceServers(
  cameraId: string,
  mediaSessionId: string
): Promise<CameraIceServers> {
  const params = new URLSearchParams({
    media_session_id: mediaSessionId
  })
  return apiRequest<CameraIceServers>(
    `/cameras/${encodeURIComponent(cameraId)}/live/ice?${params}`
  )
}


export interface CameraWhepSession {
  answerSdp: string
  location: string
}

async function throwLiveHttpError(
  response: Response,
  fallback: string
): Promise<never> {
  const contentType = response.headers.get("content-type") ?? ""
  let payload: ApiErrorBody | undefined
  if (contentType.includes("application/json")) {
    try {
      payload = (await response.json()) as ApiErrorBody
    } catch {
      payload = undefined
    }
  }
  const error = payload?.error
  throw new ApiClientError(
    response.status,
    error?.code ?? "http_error",
    error?.message ?? `${fallback} (${response.status})`,
    error?.details ?? {},
    error?.request_id ??
      response.headers.get("x-request-id")
  )
}

export async function createCameraWhepSession(
  cameraId: string,
  quality: LiveQuality,
  mediaSessionId: string,
  offerSdp: string
): Promise<CameraWhepSession> {
  const params = new URLSearchParams({
    quality,
    media_session_id: mediaSessionId
  })
  const response = await fetch(
    `/api/v1/cameras/${encodeURIComponent(cameraId)}/live/whep?${params}`,
    {
      method: "POST",
      headers: {
        Accept: "application/sdp",
        "Content-Type": "application/sdp"
      },
      body: offerSdp,
      credentials: "same-origin"
    }
  )

  if (!response.ok) {
    await throwLiveHttpError(
      response,
      "WebRTC negotiation failed"
    )
  }

  const contentType = response.headers.get("content-type") ?? ""
  const location = response.headers.get("location")
  const answerSdp = await response.text()
  if (
    !contentType.includes("application/sdp") ||
    !location ||
    !location.startsWith("/api/v1/") ||
    !answerSdp
  ) {
    throw new Error("WebRTC negotiation returned an invalid response.")
  }

  return { answerSdp, location }
}

export async function deleteCameraWhepSession(
  location: string
): Promise<void> {
  if (!location.startsWith("/api/v1/")) return

  const response = await fetch(location, {
    method: "DELETE",
    credentials: "same-origin"
  })
  if (!response.ok && response.status !== 404) {
    throw new Error(
      `WebRTC session cleanup failed with status ${response.status}.`
    )
  }
}


export function revokeCameraMediaSession(
  cameraId: string,
  mediaSessionId: string
): Promise<void> {
  return apiRequest<void>(
    `/cameras/${encodeURIComponent(cameraId)}/live/session/${encodeURIComponent(mediaSessionId)}`,
    { method: "DELETE" }
  )
}


export function cameraSnapshotUrl(cameraId: string): string {
  return `/api/v1/cameras/${encodeURIComponent(cameraId)}/snapshot`
}


export type LiveLayoutSlots = 1 | 4 | 9 | 16

export interface LiveViewLayoutState {
  slots: LiveLayoutSlots
  camera_ids: string[]
  camera_panel_open: boolean
}

export interface LiveViewLayout {
  id: string
  name: string
  is_default: boolean
  layout: LiveViewLayoutState
  created_at: string
  updated_at: string
}

export function listLiveViewLayouts(): Promise<LiveViewLayout[]> {
  return apiRequest<LiveViewLayout[]>("/live-layouts")
}

export function createLiveViewLayout(input: {
  name: string
  is_default?: boolean
  layout: LiveViewLayoutState
}): Promise<LiveViewLayout> {
  return apiRequest<LiveViewLayout>("/live-layouts", {
    method: "POST",
    json: input
  })
}

export function updateLiveViewLayout(
  layoutId: string,
  changes: {
    name?: string
    is_default?: boolean
    layout?: LiveViewLayoutState
  }
): Promise<LiveViewLayout> {
  return apiRequest<LiveViewLayout>(
    `/live-layouts/${encodeURIComponent(layoutId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteLiveViewLayout(
  layoutId: string
): Promise<void> {
  return apiRequest<void>(
    `/live-layouts/${encodeURIComponent(layoutId)}`,
    { method: "DELETE" }
  )
}
