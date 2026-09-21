import { apiRequest } from "./client"

export type LiveQuality = "auto" | "high" | "low"

export interface CameraLiveStream {
  camera_id: string
  profile_id: string
  purpose: "LIVE_HIGH" | "LIVE_LOW" | "RECORD"
  transport: "hls"
  transports: Array<"webrtc" | "hls">
  hls_url: string
  expires_at: string
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
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


export interface CameraWhepSession {
  answerSdp: string
  location: string
}

export async function createCameraWhepSession(
  cameraId: string,
  quality: LiveQuality,
  offerSdp: string
): Promise<CameraWhepSession> {
  const params = new URLSearchParams({ quality })
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
    throw new Error(
      `WebRTC negotiation failed with status ${response.status}.`
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
